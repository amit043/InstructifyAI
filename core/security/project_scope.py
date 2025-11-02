import uuid

from typing import Optional

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from models import Document


def get_project_scope(
    x_project_id: Optional[str] = Header(default=None),
) -> Optional[uuid.UUID]:
    """Return project UUID from header if provided."""
    if x_project_id is None:
        return None
    try:
        return uuid.UUID(x_project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid project scope") from exc


def ensure_document_scope(
    doc_id: str,
    db: Session,
    project_id: Optional[uuid.UUID],
) -> Document:
    """Fetch document and verify it belongs to scoped project."""
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    if project_id and doc.project_id != project_id:
        raise HTTPException(status_code=403, detail="forbidden")
    return doc


__all__ = ["get_project_scope", "ensure_document_scope"]
