from __future__ import annotations

import uuid
from typing import Any, Tuple

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from core.settings import get_settings
from models import Document, DocumentVersion
from services.jobs import set_progress
from storage.object_store import ObjectStore, create_client
from worker.pipeline import get_parser_settings
from worker.v1 import run_parse_v1

settings = get_settings()
engine = sa.create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _get_store() -> ObjectStore:
    client = create_client(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    return ObjectStore(client=client, bucket=settings.s3_bucket)


def orchestrate_parse(
    doc_id: str,
    version: int,
    *,
    pipeline: str,
    parser_overrides: dict | None,
    job_id: str | None,
) -> Tuple[list[dict], dict, dict, dict[str, list[dict[str, str]]], dict[str, Any]]:
    """
    Route to V1 or V2 parse implementations without changing external contracts.
    Returns (rows, metrics, meta_patch, redactions, artifacts).
    """
    db: Session = SessionLocal()
    store = _get_store()
    try:
        doc = db.get(Document, doc_id)
        if not doc:
            raise RuntimeError(f"document not found: {doc_id=}")
        dv = db.scalar(
            sa.select(DocumentVersion).where(
                DocumentVersion.document_id == doc_id,
                DocumentVersion.version == version,
            )
        )
        if not dv:
            raise RuntimeError(f"document version not found: {doc_id=} {version=}")

        if job_id:
            set_progress(db, uuid.UUID(job_id), 20)

        rows: list[dict]
        metrics: dict
        meta_patch: dict
        redactions: dict[str, list[dict[str, str]]]
        artifacts: dict[str, Any] = {}

        source_type = (doc.source_type or "").lower()
        mime = (dv.mime or "").lower()
        is_pdf = "pdf" in mime or source_type == "pdf"
        parser_settings = get_parser_settings(doc.project)

        # Determine source hint for HTML v2
        source_hint: dict[str, Any] | None = None
        if mime == "application/zip":
            source_hint = {"zip": True}
        elif mime == "application/x-crawl" or (
            isinstance(dv.meta, dict) and dv.meta.get("base_url")
        ):
            base_url = dv.meta.get("base_url") if isinstance(dv.meta, dict) else None
            source_hint = {"base_url": base_url}

        if pipeline == "v2":
            # Lazy imports to avoid optional dep issues
            if is_pdf:
                from worker.pdf_v2 import parse_pdf_v2  # type: ignore

                rows, metrics, meta_patch, redactions = parse_pdf_v2(
                    db,
                    store,
                    doc,
                    dv,
                    parser_overrides=parser_overrides,
                    job_id=job_id,
                    settings=parser_settings,
                )
            else:
                from worker.html_v2 import parse_html_v2  # type: ignore

                rows, metrics, meta_patch, redactions = parse_html_v2(
                    db,
                    store,
                    doc,
                    dv,
                    parser_overrides=parser_overrides,
                    job_id=job_id,
                    settings=parser_settings,
                    source_hint=source_hint,
                )
        else:
            rows, metrics, meta_patch, redactions = run_parse_v1(
                db, store, doc, dv, parser_overrides or {}, [], False
            )

        if job_id:
            set_progress(db, uuid.UUID(job_id), 40)

        return rows, metrics, meta_patch, redactions, artifacts
    finally:
        db.close()


__all__ = ["orchestrate_parse"]
