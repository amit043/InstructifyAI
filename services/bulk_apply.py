from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from api.schemas import BulkApplyPayload
from core.correlation import get_request_id
from core.metrics import enforce_quality_gates
from core.quality import audit_action_with_conflict
from models import Audit, Chunk, Document


def apply_bulk_metadata(db: Session, payload: BulkApplyPayload) -> int:
    selection = payload.selection
    patch = payload.patch.metadata
    user = payload.user

    chunks: list[Chunk] = []
    if selection.chunk_ids:
        chunks = db.query(Chunk).filter(Chunk.id.in_(selection.chunk_ids)).all()
        if len(chunks) != len(selection.chunk_ids):
            raise HTTPException(status_code=404, detail="chunk not found")
    elif selection.doc_id and selection.range:
        start = selection.range.from_
        end = selection.range.to
        chunks = (
            db.query(Chunk)
            .filter(
                Chunk.document_id == selection.doc_id,
                Chunk.order >= start,
                Chunk.order <= end,
            )
            .all()
        )
        if not chunks:
            raise HTTPException(status_code=404, detail="no chunks found")
    else:
        raise HTTPException(status_code=400, detail="invalid selection")

    affected: set[tuple[str, str, int]] = set()
    audits: list[Audit] = []
    try:
        for chunk in chunks:
            before = dict(chunk.meta)
            new_meta = dict(before)
            new_meta.update(patch)
            chunk.meta = new_meta
            chunk.rev += 1
            action = audit_action_with_conflict(
                db, chunk.id, user, "bulk_apply", before, new_meta
            )
            audits.append(
                Audit(
                    chunk_id=chunk.id,
                    user=user,
                    action=action,
                    before=before,
                    after=new_meta,
                    request_id=get_request_id(),
                )
            )
            doc = db.get(Document, chunk.document_id)
            if doc is not None:
                affected.add((doc.id, str(doc.project_id), chunk.version))
        db.add_all(audits)
        for doc_id, proj_id, ver in affected:
            enforce_quality_gates(doc_id, proj_id, ver, db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return len(chunks)
