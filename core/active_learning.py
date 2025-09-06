from __future__ import annotations

import uuid
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.metrics import _required_fields
from core.settings import get_settings
from models import Chunk, Document

settings = get_settings()


def _has_value(meta: dict, field: str) -> bool:
    if field not in meta:
        return False
    value = meta[field]
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    return True


def score_chunk(chunk: Chunk, required: List[str]) -> List[str]:
    reasons: List[str] = []
    meta = chunk.meta or {}
    text_cov = meta.get("text_coverage")
    if text_cov is not None and text_cov < settings.text_coverage_threshold:
        reasons.append("low_text_coverage")
    ocr_conf = meta.get("ocr_conf_mean")
    if ocr_conf is not None and ocr_conf < 0.5:
        reasons.append("low_ocr_conf")
    if any(not _has_value(meta, f) for f in required):
        reasons.append("missing_required_fields")
    suggestions = meta.get("suggestions", {})
    for field, info in suggestions.items():
        if field in meta and meta[field] != info.get("value"):
            reasons.append("suggestion_conflicts")
            break
    return reasons


def next_chunks(
    project_id: str | uuid.UUID, limit: int, db: Session
) -> List[tuple[str, List[str]]]:
    if limit < 1:
        return []
    if isinstance(project_id, str):
        project_id = uuid.UUID(project_id)
    required = _required_fields(project_id, db)
    stmt = (
        select(Chunk)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.project_id == project_id)
        .order_by(Chunk.created_at)
        .limit(limit * 5)
    )
    chunks = db.scalars(stmt)
    entries: List[tuple[str, List[str]]] = []
    for ch in chunks:
        reasons = score_chunk(ch, required)
        if reasons:
            entries.append((str(ch.id), reasons))
        if len(entries) >= limit:
            break
    return entries
