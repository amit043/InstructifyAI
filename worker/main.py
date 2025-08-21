from __future__ import annotations

import logging
import subprocess
from typing import Any

import sqlalchemy as sa
from celery import Celery  # type: ignore[import-untyped]
from sqlalchemy.orm import sessionmaker

from chunking.chunker import chunk_blocks
from core.correlation import set_request_id
from core.logging import configure_logging
from core.metrics import compute_parse_metrics, enforce_quality_gates
from core.settings import get_settings
from models import Document, DocumentStatus
from parsers import registry
from storage.object_store import ObjectStore, create_client, raw_key
from worker.derived_writer import upsert_chunks
from worker.suggestors import suggest

settings = get_settings()
app = Celery("worker", broker=settings.redis_url)
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
            blocks = parser_cls.parse(data)
            chunks = chunk_blocks(blocks)
            metrics = compute_parse_metrics(chunks, mime=ver.mime)
            ver.meta = {**ver.meta, "metrics": metrics}
            project = doc.project
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
            )
            enforce_quality_gates(doc_id, doc.project_id, ver.version, db)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("parse failed: %s", exc)
            ver.status = DocumentStatus.FAILED.value
            meta: dict[str, Any] = dict(ver.meta or {})
            meta["error"] = str(exc)
            ver.meta = meta
            db.commit()


if __name__ == "__main__":
    app.worker_main()
