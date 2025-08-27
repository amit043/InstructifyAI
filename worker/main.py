from __future__ import annotations

import json
import logging
import subprocess
import traceback
import uuid
from datetime import datetime
from typing import Any, cast
from urllib.parse import urljoin, urlparse

import httpx
import sqlalchemy as sa
from bs4 import BeautifulSoup, Tag
from sqlalchemy.orm import Session, sessionmaker

from chunking.chunker import chunk_blocks
from core.correlation import get_request_id, set_request_id
from core.logging import configure_logging
from core.metrics import compute_parse_metrics, enforce_quality_gates
from core.pii import detect_pii
from core.settings import get_settings
from models import Document, DocumentStatus, DocumentVersion
from parser_pipeline.metrics import char_coverage
from parsers import registry
from services.jobs import set_done, set_failed, set_progress
from storage.object_store import (
    ObjectStore,
    create_client,
    derived_key,
    raw_key,
    signed_url,
)
from worker.celery_app import app
from worker.derived_writer import upsert_chunks, write_redactions
from worker.pipeline import get_parser_settings
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


def _update_version(
    db: Session,
    version_id: str,
    *,
    status: str | None = None,
    meta_patch: dict | None = None,
) -> None:
    dv = db.get(DocumentVersion, version_id)
    if not dv:
        return
    if status is not None:
        dv.status = status
    if meta_patch:
        base = dict(dv.meta or {})
        for k, v in meta_patch.items():
            if k == "parse" and isinstance(v, dict):
                existing = dict(base.get("parse") or {})
                existing.update(v)
                base["parse"] = existing
            else:
                base[k] = v
        dv.meta = base
    db.commit()


def _run_parse(
    db: Session, store: ObjectStore, doc: Document, dv: DocumentVersion
) -> tuple[list[dict], dict, dict, dict[str, list[dict[str, str]]]]:
    filename = dv.meta.get("filename")
    if not isinstance(filename, str):
        raise RuntimeError("filename missing")
    data = store.get_bytes(raw_key(doc.id, filename))
    parser_cls = registry.get(dv.mime)
    logger.info("Picked parser: %s for %s", parser_cls.__name__, dv.mime)
    try:
        blocks = list(parser_cls.parse(data, store=store, doc_id=doc.id))  # type: ignore[call-arg]
    except TypeError:
        blocks = list(parser_cls.parse(data))
    chunks = chunk_blocks(blocks)
    extracted_text = "".join(b.text for b in blocks if getattr(b, "text", ""))
    coverage = char_coverage(extracted_text)
    metrics = compute_parse_metrics(chunks, mime=dv.mime)
    metrics["text_coverage"] = coverage["ascii_ratio"] + coverage["latin1_ratio"]
    metrics["utf_other_ratio"] = coverage["other_ratio"]

    project = doc.project
    parser_settings = get_parser_settings(project)
    parse_meta: dict = {"char_coverage_extracted": coverage}
    meta_patch = {
        "metrics": metrics,
        "parser_settings": parser_settings,
        "parse": parse_meta,
    }

    if project.use_rules_suggestor or project.use_mini_llm:
        total = 0
        for ch in chunks:
            if ch.content.type != "text":
                continue
            remaining = (
                project.max_suggestions_per_doc or settings.max_suggestions_per_doc
            ) - total
            if remaining <= 0:
                break
            sugg = suggest(
                ch.content.text or "",
                use_rules_suggestor=project.use_rules_suggestor,
                use_mini_llm=project.use_mini_llm,
                max_suggestions=remaining,
                suggestion_timeout_ms=(
                    project.suggestion_timeout_ms or settings.suggestion_timeout_ms
                ),
            )
            if sugg:
                ch.metadata.setdefault("suggestions", {})
                for key, val in sugg.items():
                    ch.metadata["suggestions"][key] = val
                total += len(sugg)

    redactions: dict[str, list[dict[str, str]]] = {}
    total_pii = 0
    for ch in chunks:
        if ch.content.type != "text":
            continue
        matches = detect_pii(ch.content.text or "")
        if matches:
            ch.metadata.setdefault("suggestions", {})
            ch.metadata["suggestions"]["redactions"] = [
                {"type": m.type, "text": m.text} for m in matches
            ]
            redactions[str(ch.id)] = [{"type": m.type, "text": m.text} for m in matches]
            total_pii += len(matches)
    metrics["pii_count"] = total_pii

    rows = [
        {
            "id": str(ch.id),
            "document_id": doc.id,
            "version": dv.version,
            "order": ch.order,
            "text": ch.content.text,
            "text_hash": ch.text_hash,
            "meta": {
                **ch.metadata,
                "content_type": ch.content.type,
                "page": ch.source.page,
                "section_path": ch.source.section_path,
            },
        }
        for ch in chunks
    ]
    parse_meta["counts"] = {"chunks": len(rows)}
    return rows, metrics, meta_patch, redactions


@app.task
def crawl_document(
    doc_id: str,
    base_url: str,
    allow_prefix: str | None,
    max_depth: int,
    max_pages: int,
    request_id: str | None = None,
    job_id: str | None = None,
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
    parse_document.delay(doc_id, request_id=get_request_id(), job_id=job_id)


@app.task
def parse_document(
    doc_id: str, request_id: str | None = None, job_id: str | None = None
) -> None:
    set_request_id(request_id)
    store = _get_store()
    db: Session = SessionLocal()
    rid = request_id or get_request_id() or "no-rid"
    try:
        doc = db.get(Document, doc_id)
        if not doc or not doc.latest_version_id:
            raise RuntimeError(f"document or latest version missing: {doc_id=}")
        dv = db.get(DocumentVersion, doc.latest_version_id)
        if not dv:
            raise RuntimeError(f"document version not found: {doc.latest_version_id}")

        _update_version(
            db,
            dv.id,
            status=DocumentStatus.PARSING.value,
            meta_patch={"request_id": rid},
        )
        if job_id:
            set_progress(db, uuid.UUID(job_id), 10)

        rows, metrics, meta_patch, redactions = _run_parse(db, store, doc, dv)

        if job_id:
            set_progress(db, uuid.UUID(job_id), 50)

        chunks_url, manifest_url, deltas = upsert_chunks(
            db,
            store,
            doc_id=doc.id,
            version=dv.version,
            rows=rows,
            metrics=metrics,
        )

        write_redactions(store, doc.id, redactions)
        enforce_quality_gates(doc.id, doc.project_id, dv.version, db)

        if job_id:
            set_progress(db, uuid.UUID(job_id), 90)

        meta_patch["parse"]["deltas"] = deltas
        parse_summary = {
            **meta_patch["parse"],
            "chunks_url": chunks_url,
            "manifest_url": manifest_url,
            "deltas": deltas,
            "metrics": metrics or {},
        }
        meta_patch["parse"] = parse_summary

        _update_version(
            db,
            dv.id,
            status=DocumentStatus.PARSED.value,
            meta_patch=meta_patch,
        )

        if job_id:
            set_done(
                db,
                uuid.UUID(job_id),
                {"chunks_url": chunks_url, "manifest_url": manifest_url},
            )

    except Exception as e:
        db.rollback()
        tb = traceback.format_exc()
        err_key = derived_key(
            doc_id, f"errors/{datetime.utcnow().isoformat()}_{rid}.log"
        )
        store.put_bytes(err_key, tb.encode("utf-8"))
        err_url = signed_url(store, err_key)
        try:
            doc = db.get(Document, doc_id)
            dv_id = getattr(doc, "latest_version_id", None)
            if dv_id:
                _update_version(
                    db,
                    dv_id,
                    status=DocumentStatus.FAILED.value,
                    meta_patch={
                        "error": str(e)[:2000],
                        "error_artifact": err_url,
                        "request_id": rid,
                    },
                )
            if job_id:
                set_failed(
                    db, uuid.UUID(job_id), str(e)[:2000], {"error_artifact": err_url}
                )
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    app.worker_main()
