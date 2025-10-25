from __future__ import annotations

import uuid
from typing import Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from models.adapter_binding import AdapterBinding


def _coerce_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


def _normalize_document_id(value: str | uuid.UUID | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _apply_scope_filters(
    stmt: sa.Select, *, project_id: uuid.UUID | None, document_id: str | None, tag: str | None
) -> sa.Select:
    if project_id is None:
        stmt = stmt.where(AdapterBinding.project_id.is_(None))
    else:
        stmt = stmt.where(AdapterBinding.project_id == project_id)

    if document_id is None:
        stmt = stmt.where(AdapterBinding.document_id.is_(None))
    else:
        stmt = stmt.where(AdapterBinding.document_id == document_id)

    if tag is None:
        stmt = stmt.where(AdapterBinding.tag.is_(None))
    else:
        stmt = stmt.where(AdapterBinding.tag == tag)
    return stmt


def _sort_bindings(bindings: Sequence[AdapterBinding]) -> list[AdapterBinding]:
    return sorted(
        bindings,
        key=lambda b: (
            b.priority,
            -(b.created_at.timestamp() if b.created_at else 0.0),
        ),
    )


def register_binding(
    db: Session,
    *,
    backend: str,
    base_model: str,
    model_ref: str,
    project_id: str | uuid.UUID | None = None,
    document_id: str | uuid.UUID | None = None,
    adapter_path: str | None = None,
    tag: str | None = None,
    priority: int = 100,
    enabled: bool = True,
) -> AdapterBinding:
    if project_id is None and document_id is None:
        raise ValueError("project_id or doc_id must be provided")

    pid = _coerce_uuid(project_id)
    did = _normalize_document_id(document_id)

    stmt = sa.select(AdapterBinding).where(AdapterBinding.model_ref == model_ref)
    stmt = _apply_scope_filters(stmt, project_id=pid, document_id=did, tag=tag)
    existing = db.execute(stmt).scalar_one_or_none()

    if existing:
        existing.backend = backend
        existing.base_model = base_model
        existing.adapter_path = adapter_path
        existing.priority = priority
        existing.enabled = enabled
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    binding = AdapterBinding(
        project_id=pid,
        document_id=did,
        backend=backend,
        base_model=base_model,
        adapter_path=adapter_path,
        model_ref=model_ref,
        tag=tag,
        priority=priority,
        enabled=enabled,
    )
    db.add(binding)
    db.commit()
    db.refresh(binding)
    return binding


def get_bindings(
    db: Session,
    *,
    project_id: str | uuid.UUID,
    document_id: str | uuid.UUID | None = None,
    top_k: int = 2,
) -> list[AdapterBinding]:
    pid = _coerce_uuid(project_id)
    if pid is None:
        raise ValueError("project_id is required")
    did = _normalize_document_id(document_id)

    limit = max(1, top_k or 1)
    base_query = (
        sa.select(AdapterBinding)
        .where(AdapterBinding.enabled.is_(True))
        .order_by(AdapterBinding.priority.asc(), AdapterBinding.created_at.desc())
        .limit(limit)
    )

    if did is not None:
        doc_query = base_query.where(AdapterBinding.document_id == did)
        doc_rows = db.scalars(doc_query).all()
        if doc_rows:
            return list(doc_rows)

    project_query = base_query.where(
        AdapterBinding.project_id == pid,
        AdapterBinding.document_id.is_(None),
    )
    proj_rows = db.scalars(project_query).all()
    if proj_rows:
        return list(proj_rows)
    return []


def get_bindings_by_refs(
    db: Session,
    *,
    project_id: str | uuid.UUID,
    refs: Sequence[str],
    document_id: str | uuid.UUID | None = None,
) -> list[AdapterBinding]:
    if not refs:
        return []

    pid = _coerce_uuid(project_id)
    did = _normalize_document_id(document_id)

    stmt = sa.select(AdapterBinding).where(
        AdapterBinding.enabled.is_(True),
        AdapterBinding.model_ref.in_(tuple(refs)),
    )
    if pid is not None:
        stmt = stmt.where(
            sa.or_(AdapterBinding.project_id == pid, AdapterBinding.project_id.is_(None))
        )
    rows = db.scalars(stmt).all()

    selected: list[AdapterBinding] = []
    for ref in refs:
        matches = [row for row in rows if row.model_ref == ref]
        if did is not None:
            doc_matches = [row for row in matches if row.document_id == did]
            if doc_matches:
                matches = doc_matches
        if pid is not None:
            proj_matches = [row for row in matches if row.project_id == pid]
            if proj_matches:
                matches = proj_matches
        if matches:
            selected.append(_sort_bindings(matches)[0])
    return selected


__all__ = ["AdapterBinding", "register_binding", "get_bindings", "get_bindings_by_refs"]
