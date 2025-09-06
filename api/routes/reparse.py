from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from api.db import get_db
from api.deps import require_curator
from core.correlation import new_request_id
from models import Document
from worker.main import reparse_document


router = APIRouter()


@router.post("/documents/{doc_id}/reparse")
def reparse_endpoint(
    doc_id: str,
    request: Request,
    pipeline: Literal["v1", "v2"] | None = None,
    force: bool = False,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> JSONResponse:
    # Validate document exists
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")

    rid = request.headers.get("X-Request-ID") or new_request_id()
    # Enqueue reparse task
    async_result = reparse_document.delay(doc_id, pipeline, force, rid)
    return JSONResponse(status_code=202, content={"task_id": async_result.id})

