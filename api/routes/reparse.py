from __future__ import annotations

from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from api.db import get_db
from models import Document, DocumentStatus, DocumentVersion
from worker.main import parse_document


router = APIRouter()


@router.post("/documents/{doc_id}/reparse")
def reparse_endpoint(
    doc_id: str,
    request: Request,
    pipeline: Literal["v1", "v2"] | None = None,
    force_version_bump: bool = False,
    db: Session = Depends(get_db),
) -> JSONResponse:
    # Validate document exists
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")

    latest = db.scalar(
        sa.select(DocumentVersion)
        .where(DocumentVersion.document_id == doc_id)
        .order_by(DocumentVersion.version.desc())
        .limit(1)
    )
    if latest is None:
        raise HTTPException(status_code=400, detail="no version to reparse")

    if force_version_bump:
        new_ver = (latest.version or 0) + 1
        dv = DocumentVersion(
            document_id=doc_id,
            project_id=latest.project_id,
            version=new_ver,
            doc_hash=latest.doc_hash,
            mime=latest.mime,
            size=latest.size,
            status=DocumentStatus.INGESTED.value,
            meta=dict(latest.meta or {}),
        )
        db.add(dv)
        db.flush()
        doc.latest_version_id = dv.id
        db.commit()
        version_to_parse = dv.version
    else:
        latest.status = DocumentStatus.INGESTED.value
        db.add(latest)
        db.commit()
        version_to_parse = latest.version

    # Enqueue parse of the chosen version (tests stub .delay)
    parse_document.delay(doc_id, version_to_parse, pipeline=pipeline)
    return JSONResponse(status_code=200, content={"doc_id": doc_id, "version": version_to_parse})
