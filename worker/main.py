from __future__ import annotations

import json
import logging
import subprocess
from typing import Any, cast
from urllib.parse import urljoin, urlparse

import httpx
import sqlalchemy as sa
from bs4 import BeautifulSoup, Tag
from sqlalchemy.orm import sessionmaker

from chunking.chunker import chunk_blocks
from core.correlation import get_request_id, set_request_id
from core.logging import configure_logging
from core.metrics import compute_parse_metrics, enforce_quality_gates
from core.settings import get_settings
from models import Document, DocumentStatus
from parser_pipeline.metrics import char_coverage
from parsers import registry
from storage.object_store import ObjectStore, create_client, raw_key
from worker.celery_app import app
from worker.derived_writer import upsert_chunks
from worker.pipeline import get_parser_settings
from worker.pipeline.incremental import plan_deltas
from worker.suggestors import suggest

settings = get_settings()
engine = sa.create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

configure_logging()
logger = logging.getLogger(__name__)

try:
    version = subprocess.check_output(
        ["tesseract", "--version"], text=True
    ).splitlines()[0]
    logger.info("tesseract --version: %s", version)
except Exception as exc:  # noqa: BLE001
    logger.warning("tesseract --version failed: %s", exc)


def _get_store() -> ObjectStore:
    client = create_client(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    return ObjectStore(client=client, bucket=settings.s3_bucket)


@app.task
def crawl_document(
    doc_id: str,
    base_url: str,
    allow_prefix: str | None,
    max_depth: int,
    max_pages: int,
    request_id: str | None = None,
) -> None:
    set_request_id(request_id)
    store = _get_store()
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(base_url, 0)]
    index: dict[str, str] = {}
    parsed_base = urlparse(base_url)
    host = parsed_base.netloc
    while queue and len(index) < max_pages:
        url, depth = queue.pop(0)
        if url in visited or depth > max_depth:
            continue
        visited.add(url)
        try:
            resp = httpx.get(url, follow_redirects=True)
            if resp.status_code != 200:
                continue
            if "text/html" not in resp.headers.get("content-type", ""):
                continue
        except Exception:  # noqa: BLE001
            continue
        filename = f"page{len(index)}.html"
        store.put_bytes(raw_key(doc_id, f"crawl/{filename}"), resp.content)
        index[url] = filename
        if depth < max_depth:
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                if not isinstance(a, Tag):
                    continue
                link = a.get("href")
                if not link:
                    continue
                link = cast(str, link)
                nxt = urljoin(url, link)
                parsed = urlparse(nxt)
                if parsed.netloc != host:
                    continue
                if allow_prefix and not parsed.path.startswith(allow_prefix):
                    continue
                if nxt not in visited and all(nxt != q[0] for q in queue):
                    queue.append((nxt, depth + 1))
    store.put_bytes(
        raw_key(doc_id, "crawl/crawl_index.json"),
        json.dumps(index).encode("utf-8"),
    )
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        if doc and doc.latest_version:
            ver = doc.latest_version
            meta = dict(ver.meta)
            meta["file_count"] = len(index)
            ver.meta = meta
            db.commit()
    parse_document.delay(doc_id, request_id=get_request_id())


@app.task
def parse_document(doc_id: str, request_id: str | None = None) -> None:
    set_request_id(request_id)
    store = _get_store()
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        if doc is None or doc.latest_version is None:
            return
        ver = doc.latest_version
        filename = ver.meta.get("filename")
        try:
            data = store.get_bytes(raw_key(doc_id, filename))
            parser_cls = registry.get(ver.mime)
            logger.info("Picked parser: %s for %s", parser_cls.__name__, ver.mime)
            try:
                blocks = list(parser_cls.parse(data, store=store, doc_id=doc_id))  # type: ignore[call-arg]
            except TypeError:
                blocks = list(parser_cls.parse(data))
            chunks = chunk_blocks(blocks)
            extracted_text = "".join(b.text for b in blocks if getattr(b, "text", ""))
            prev_parts = ver.meta.get("parse", {}).get("parts", {})
            parts, deltas = plan_deltas(blocks, prev_parts)
            coverage = char_coverage(extracted_text)
            metrics = compute_parse_metrics(chunks, mime=ver.mime)
            metrics["text_coverage"] = (
                coverage["ascii_ratio"] + coverage["latin1_ratio"]
            )
            metrics["utf_other_ratio"] = coverage["other_ratio"]
            meta = dict(ver.meta)
            project = doc.project
            parser_settings = get_parser_settings(project)
            parse_meta = dict(meta.get("parse", {}))
            parse_meta["char_coverage_extracted"] = coverage
            parse_meta["parts"] = parts
            meta["parse"] = parse_meta
            meta["metrics"] = metrics
            meta["parser_settings"] = parser_settings
            ver.meta = meta
            if project.use_rules_suggestor or project.use_mini_llm:
                total = 0
                for ch in chunks:
                    if ch.content.type != "text":
                        continue
                    remaining = (
                        project.max_suggestions_per_doc
                        or settings.max_suggestions_per_doc
                    ) - total
                    if remaining <= 0:
                        break
                    sugg = suggest(
                        ch.content.text or "",
                        use_rules_suggestor=project.use_rules_suggestor,
                        use_mini_llm=project.use_mini_llm,
                        max_suggestions=remaining,
                        suggestion_timeout_ms=(
                            project.suggestion_timeout_ms
                            or settings.suggestion_timeout_ms
                        ),
                    )
                    if sugg:
                        ch.metadata.setdefault("suggestions", {})
                        for key, val in sugg.items():
                            ch.metadata["suggestions"][key] = val
                        total += len(sugg)
            ver.status = DocumentStatus.PARSED.value
            db.add(ver)
            upsert_chunks(
                db,
                store,
                doc_id=doc_id,
                version=ver.version,
                chunks=chunks,
                metrics=metrics,
                parts=parts,
                deltas=deltas,
            )
            enforce_quality_gates(doc_id, doc.project_id, ver.version, db)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("parse failed: %s", exc)
            ver.status = DocumentStatus.FAILED.value
            err_meta: dict[str, Any] = dict(ver.meta or {})
            err_meta["error"] = str(exc)
            ver.meta = err_meta
            db.commit()


if __name__ == "__main__":
    app.worker_main()
