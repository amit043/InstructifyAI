from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from io import BytesIO
from typing import Any
from zipfile import ZipFile

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from api.db import get_db
from core.correlation import get_request_id
from core.settings import get_settings
from models import Document, DocumentStatus, DocumentVersion, Project
from parsers.html_parser import crawl_from, parse_dir, parse_single, parse_zip
from observability.metrics import INGEST_REQUESTS
from storage.object_store import (
    ObjectStore,
    create_client,
    derived_key,
    raw_bundle_key,
    raw_key,
)
from worker.derived_writer import upsert_chunks

from core.security.project_scope import get_project_scope


router = APIRouter()


def _ensure_project(db: Session, project_id: str, project_scope: uuid.UUID | None) -> Project:
    try:
        proj_uuid = uuid.UUID(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    if project_scope and project_scope != proj_uuid:
        raise HTTPException(status_code=403, detail="forbidden")
    project = db.get(Project, proj_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if not project.is_active:
        raise HTTPException(status_code=400, detail="project is inactive")
    return project


def _get_object_store() -> ObjectStore:
    s = get_settings()
    client = create_client(
        endpoint=s.minio_endpoint,
        access_key=s.minio_access_key,
        secret_key=s.minio_secret_key,
        secure=s.minio_secure,
    )
    return ObjectStore(client=client, bucket=s.s3_bucket)


@router.post("/ingest/html")
async def ingest_html(
    request: Request,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(_get_object_store),
    project_scope: uuid.UUID | None = Depends(get_project_scope),
) -> dict[str, Any]:
    INGEST_REQUESTS.inc()
    settings = get_settings()
    mode = "json"
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        mode = "multipart"

    if mode == "multipart":
        form = await request.form()
        upload = form.get("file")
        project_field = form.get("project_id")
        if upload is None or project_field is None:
            raise HTTPException(status_code=400, detail="project_id and file required")
        data = await upload.read()  # type: ignore[call-arg, union-attr]
        project = _ensure_project(db, str(project_field), project_scope)

        # dedupe by zip bytes
        try:
            with ZipFile(BytesIO(data)) as zf:
                html_files = [f for f in zf.namelist() if f.lower().endswith(".html")]
        except Exception:
            raise HTTPException(status_code=400, detail="invalid zip file")

        doc_hash = hashlib.sha256(data).hexdigest()
        existing = db.scalar(
            sa.select(DocumentVersion).where(
                DocumentVersion.project_id == project.id,
                DocumentVersion.doc_hash == doc_hash,
            )
        )
        if existing is not None:
            return {"doc_id": str(existing.document_id)}

        document = Document(project_id=project.id, source_type="html_bundle")
        db.add(document)
        db.flush()

        version = DocumentVersion(
            document_id=document.id,
            project_id=project.id,
            version=1,
            doc_hash=doc_hash,
            mime="application/zip",
            size=len(data),
            status=DocumentStatus.INGESTED.value,
            meta={"filename": "bundle.zip", "file_count": len(html_files)},
        )
        db.add(version)
        db.flush()
        document.latest_version_id = version.id
        db.commit()

        # Store raw zip
        store.put_bytes(raw_bundle_key(str(document.id)), data)

        # Materialize to temp dir for parsing
        with tempfile.TemporaryDirectory() as td:
            zf = ZipFile(BytesIO(data))
            zf.extractall(td)
            rows = parse_dir(td, project_id=project.id)

        upsert_chunks(db, store, doc_id=document.id, version=1, rows=rows, metrics={})
        return {"doc_id": str(document.id)}

    # JSON mode
    payload = await request.json()
    project_id = payload.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")
    project = _ensure_project(db, project_id, project_scope)

    uri: str | None = payload.get("uri")
    dir_path: str | None = payload.get("dir_path")
    crawl: bool = bool(payload.get("crawl", False))
    max_depth = int(payload.get("max_depth", settings.html_crawl_max_depth))
    max_pages = int(payload.get("max_pages", settings.html_crawl_max_pages))

    if dir_path:
        # Directory mode (server-side path)
        if not os.path.isdir(dir_path):
            raise HTTPException(status_code=400, detail="dir_path not found")
        # Simple dedupe via dir listing hash
        names = []
        for root, _dirs, files in os.walk(dir_path):
            for f in files:
                if f.lower().endswith(".html"):
                    names.append(os.path.relpath(os.path.join(root, f), dir_path))
        doc_hash = hashlib.sha256("|".join(sorted(names)).encode("utf-8")).hexdigest()
        existing = db.scalar(
            sa.select(DocumentVersion).where(
                DocumentVersion.project_id == project.id,
                DocumentVersion.doc_hash == doc_hash,
            )
        )
        if existing is not None:
            return {"doc_id": str(existing.document_id)}
        document = Document(project_id=project.id, source_type="html_dir")
        db.add(document)
        db.flush()
        version = DocumentVersion(
            document_id=document.id,
            project_id=project.id,
            version=1,
            doc_hash=doc_hash,
            mime="text/html",
            size=0,
            status=DocumentStatus.INGESTED.value,
            meta={"dir_path": dir_path},
        )
        db.add(version)
        db.flush()
        document.latest_version_id = version.id
        db.commit()

        rows = parse_dir(dir_path, project_id=project.id)
        upsert_chunks(db, store, doc_id=document.id, version=1, rows=rows, metrics={})
        return {"doc_id": str(document.id)}

    if not uri:
        raise HTTPException(status_code=400, detail="uri or dir_path required")

    if crawl:
        # Dedup by base url string
        doc_hash = hashlib.sha256(uri.encode("utf-8")).hexdigest()
        existing = db.scalar(
            sa.select(DocumentVersion).where(
                DocumentVersion.project_id == project.id,
                DocumentVersion.doc_hash == doc_hash,
            )
        )
        if existing is not None:
            return {"doc_id": str(existing.document_id)}
        document = Document(project_id=project.id, source_type="html_crawl")
        db.add(document)
        db.flush()
        version = DocumentVersion(
            document_id=document.id,
            project_id=project.id,
            version=1,
            doc_hash=doc_hash,
            mime="application/x-crawl",
            size=0,
            status=DocumentStatus.INGESTED.value,
            meta={"filename": "crawl/crawl_index.json", "base_url": uri},
        )
        db.add(version)
        db.flush()
        document.latest_version_id = version.id
        db.commit()

        rows = crawl_from(uri, max_depth, max_pages, project_id=project.id)
        # Include crawl limits in metrics for manifest
        metrics = {"html_crawl_limits": {"max_depth": max_depth, "max_pages": max_pages}}
        upsert_chunks(db, store, doc_id=document.id, version=1, rows=rows, metrics=metrics)
        return {"doc_id": str(document.id)}

    # Single URL mode
    # Dedup by content bytes fetched
    import urllib.request

    with urllib.request.urlopen(uri) as resp:  # noqa: S310
        data = resp.read()
    doc_hash = hashlib.sha256(data).hexdigest()
    existing = db.scalar(
        sa.select(DocumentVersion).where(
            DocumentVersion.project_id == project.id,
            DocumentVersion.doc_hash == doc_hash,
        )
    )
    if existing is not None:
        return {"doc_id": str(existing.document_id)}

    document = Document(project_id=project.id, source_type="html")
    db.add(document)
    db.flush()
    version = DocumentVersion(
        document_id=document.id,
        project_id=project.id,
        version=1,
        doc_hash=doc_hash,
        mime="text/html",
        size=len(data),
        status=DocumentStatus.INGESTED.value,
        meta={"filename": "index.html", "uri": uri},
    )
    db.add(version)
    db.flush()
    document.latest_version_id = version.id
    db.commit()

    # Store raw page
    store.put_bytes(raw_key(str(document.id), "index.html"), data)

    rows = parse_single(uri, project_id=project.id)
    upsert_chunks(db, store, doc_id=document.id, version=1, rows=rows, metrics={})
    return {"doc_id": str(document.id)}
