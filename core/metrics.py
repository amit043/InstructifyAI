from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from chunking.chunker import Chunk as ParsedChunk
from core.settings import get_settings
from models import Chunk, DocumentStatus, DocumentVersion, Project, Taxonomy
from ops.metrics import curation_completeness as completeness_gauge
from ops.metrics import (
    gate_failures,
    ocr_hit_ratio,
)


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
    pages_total: set[int] = set()
    pages_ocr: set[int] = set()
    for ch in chunk_list:
        text = ch.content.text if ch.content.type == "text" else None
        if ch.content.type != "table_placeholder" and (
            text is None or text.strip() == ""
        ):
            empty += 1
        if ch.source.section_path:
            with_section += 1
        if ch.source.page is not None:
            pages_total.add(ch.source.page)
            if ch.metadata.get("source_stage") == "pdf_ocr":
                pages_ocr.add(ch.source.page)
    ocr_ratio = len(pages_ocr) / len(pages_total) if pages_total else 0.0
    ocr_hit_ratio.set(ocr_ratio)
    return {
        "empty_chunk_ratio": empty / total,
        "html_section_path_coverage": with_section / total,
        "ocr_ratio": ocr_ratio,
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
    completeness_gauge.set(completeness)
    dv.meta = {**dv.meta, "metrics": metrics}

    breach = False
    empty_ratio = metrics.get("empty_chunk_ratio")
    if empty_ratio is not None and empty_ratio > settings.empty_chunk_ratio_threshold:
        breach = True
        gate_failures.labels("empty_chunk_ratio").inc()
    section_cov = metrics.get("html_section_path_coverage")
    if dv.mime == "text/html" and (
        section_cov is None
        or section_cov < settings.html_section_path_coverage_threshold
    ):
        breach = True
        gate_failures.labels("html_section_path_coverage").inc()
    text_cov = metrics.get("text_coverage")
    if text_cov is not None and text_cov < settings.text_coverage_threshold:
        breach = True
        gate_failures.labels("text_coverage").inc()
    ocr_ratio = metrics.get("ocr_ratio")
    if ocr_ratio is not None and ocr_ratio > settings.ocr_ratio_threshold:
        breach = True
        gate_failures.labels("ocr_ratio").inc()
    utf_other = metrics.get("utf_other_ratio")
    if utf_other is not None and utf_other > settings.utf_other_ratio_threshold:
        breach = True
        gate_failures.labels("utf_other_ratio").inc()
    if completeness < settings.curation_completeness_threshold:
        breach = True
        gate_failures.labels("curation_completeness").inc()
    proj = db.get(Project, project_id)
    if proj and proj.block_pii and metrics.get("pii_count"):
        breach = True
        gate_failures.labels("pii_count").inc()
    dv.status = (
        DocumentStatus.NEEDS_REVIEW.value if breach else DocumentStatus.PARSED.value
    )
    db.add(dv)
