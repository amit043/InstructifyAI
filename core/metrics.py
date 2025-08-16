from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.settings import get_settings
from models import Chunk, DocumentStatus, DocumentVersion, Taxonomy


def _required_fields(project_id: uuid.UUID | str, db: Session) -> list[str]:
    tax = db.scalar(
        select(Taxonomy)
        .where(Taxonomy.project_id == project_id)
        .order_by(Taxonomy.version.desc())
        .limit(1)
    )
    if tax is None:
        return []
    return [f["name"] for f in tax.fields if f.get("required")]


def _has_value(meta: dict, field: str) -> bool:
    if field not in meta:
        return False
    value = meta[field]
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    return True


def compute_curation_completeness(
    doc_id: uuid.UUID | str,
    project_id: uuid.UUID | str,
    version: int,
    db: Session,
) -> float:
    required = _required_fields(project_id, db)
    chunks: Iterable[Chunk] = db.scalars(
        select(Chunk).where(Chunk.document_id == doc_id, Chunk.version == version)
    )
    chunk_list = list(chunks)
    total = len(chunk_list)
    if total == 0:
        return 0.0
    if not required:
        return 1.0
    complete = 0
    for c in chunk_list:
        if all(_has_value(c.meta, field) for field in required):
            complete += 1
    return complete / total


def enforce_quality_gates(
    doc_id: uuid.UUID | str,
    project_id: uuid.UUID | str,
    version: int,
    db: Session,
) -> None:
    settings = get_settings()
    dv = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == doc_id,
            DocumentVersion.version == version,
        )
    )
    if dv is None:
        return
    completeness = compute_curation_completeness(doc_id, project_id, version, db)
    metrics = dict(dv.meta.get("metrics", {}))
    metrics["curation_completeness"] = completeness
    dv.meta = {**dv.meta, "metrics": metrics}
    dv.status = (
        DocumentStatus.NEEDS_REVIEW.value
        if completeness < settings.curation_completeness_threshold
        else DocumentStatus.PARSED.value
    )
    db.add(dv)
