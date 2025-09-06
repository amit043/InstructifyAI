from __future__ import annotations

import sqlalchemy as sa

from core.correlation import set_request_id
from models import Audit, DocumentVersion
from worker.main import SessionLocal


def update_status(
    doc_id: str,
    status: str,
    request_id: str | None,
    *,
    action: str | None = None,
) -> None:
    """Update DocumentVersion.status and append an audit."""
    set_request_id(request_id)
    with SessionLocal() as db:
        dv = db.scalar(
            sa.select(DocumentVersion).where(DocumentVersion.document_id == doc_id)
        )
        if dv is None:
            return
        before = {"status": dv.status}
        dv.status = status
        db.add(dv)
        db.add(
            Audit(
                chunk_id=doc_id,
                user="system",
                action=action or status,
                before=before,
                after={"status": status},
                request_id=request_id,
            )
        )
        db.commit()
