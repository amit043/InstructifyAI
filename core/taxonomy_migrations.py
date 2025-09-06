from __future__ import annotations

import uuid
from typing import Dict

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.correlation import get_request_id
from core.metrics import enforce_quality_gates
from core.quality import audit_action_with_conflict
from models import Audit, Chunk, Document, Taxonomy


def rename_enum_values(
    db: Session,
    project_id: str,
    field: str,
    mapping: Dict[str, str],
    user: str,
) -> int:
    """Rename enum options and migrate existing chunk metadata.

    Returns number of chunks updated.
    """
    try:
        proj_uuid = uuid.UUID(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")

    tax = db.scalar(
        select(Taxonomy)
        .where(Taxonomy.project_id == proj_uuid)
        .order_by(Taxonomy.version.desc())
        .limit(1)
    )
    if tax is None:
        raise HTTPException(status_code=404, detail="taxonomy not found")

    new_fields = []
    target_field = None
    for f in tax.fields:
        if f.get("name") == field:
            target_field = f
            break
    if target_field is None:
        raise HTTPException(status_code=404, detail="field not found")
    if target_field.get("type") != "enum":
        raise HTTPException(status_code=400, detail="field not enum")

    options = target_field.get("options") or []
    for old in mapping:
        if old not in options:
            raise HTTPException(status_code=400, detail=f"unknown option: {old}")
    updated_options = [mapping.get(opt, opt) for opt in options]
    seen: list[str] = []
    for opt in updated_options:
        if opt not in seen:
            seen.append(opt)
    target_field = {**target_field, "options": seen}
    for f in tax.fields:
        if f.get("name") == field:
            new_fields.append(target_field)
        else:
            new_fields.append(f)
    tax.fields = new_fields

    # migrate chunks
    rows = (
        db.query(Chunk, Document)
        .join(Document, Chunk.document_id == Document.id)
        .filter(Document.project_id == proj_uuid)
        .all()
    )
    audits: list[Audit] = []
    affected: set[tuple[str, str, int]] = set()
    count = 0
    for chunk, doc in rows:
        before = dict(chunk.meta)
        val = before.get(field)
        if val in mapping:
            after = dict(before)
            after[field] = mapping[val]
            after["stale"] = True
            chunk.meta = after
            chunk.rev += 1
            action = audit_action_with_conflict(
                db, chunk.id, user, "taxonomy_migration", before, after
            )
            audits.append(
                Audit(
                    chunk_id=chunk.id,
                    user=user,
                    action=action,
                    before=before,
                    after=after,
                    request_id=get_request_id(),
                )
            )
            affected.add((chunk.document_id, str(doc.project_id), chunk.version))
            count += 1
    try:
        db.add_all(audits)
        for doc_id, proj_id, ver in affected:
            enforce_quality_gates(doc_id, proj_id, ver, db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return count
