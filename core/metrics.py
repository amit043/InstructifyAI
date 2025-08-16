from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from chunking.chunker import Chunk as ParsedChunk
from core.settings import get_settings
from models import Chunk, DocumentStatus, DocumentVersion, Taxonomy


def _required_fields(project_id: uuid.UUID | str, db: Session) -> list[str]:
    if isinstance(project_id, str):
        project_id = uuid.UUID(project_id)
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


def compute_parse_metrics(
    chunks: Iterable[ParsedChunk],
    *,
    mime: str,
) -> dict[str, float]:
    chunk_list = list(chunks)
    total = len(chunk_list)
    if total == 0:
        return {
            "empty_chunk_ratio": 0.0,
            "html_section_path_coverage": 0.0,
        }
    empty = 0
    with_section = 0
    for ch in chunk_list:
        text = ch.content.text if ch.content.type == "text" else None
        if ch.content.type != "table_placeholder" and (
            text is None or text.strip() == ""
        ):
            empty += 1
        if ch.source.section_path:
            with_section += 1
    return {
        "empty_chunk_ratio": empty / total,
        "html_section_path_coverage": with_section / total,
    }


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
    metrics = dict(dv.meta.get("metrics", {}))
    completeness = compute_curation_completeness(doc_id, project_id, version, db)
    metrics["curation_completeness"] = completeness
    dv.meta = {**dv.meta, "metrics": metrics}

    breach = False
    empty_ratio = metrics.get("empty_chunk_ratio")
    if empty_ratio is not None and empty_ratio > settings.empty_chunk_ratio_threshold:
        breach = True
    section_cov = metrics.get("html_section_path_coverage")
    if dv.mime == "text/html" and (
        section_cov is None
        or section_cov < settings.html_section_path_coverage_threshold
    ):
        breach = True
    if completeness < settings.curation_completeness_threshold:
        breach = True
    dv.status = (
        DocumentStatus.NEEDS_REVIEW.value if breach else DocumentStatus.PARSED.value
    )
    db.add(dv)
