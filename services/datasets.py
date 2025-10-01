from __future__ import annotations

import io
import json

import sqlalchemy as sa
from sqlalchemy.orm import Session

from models import Chunk, Dataset, Document
from storage.object_store import ObjectStore, dataset_snapshot_key


def materialize_dataset_snapshot(db: Session, store: ObjectStore, dataset: Dataset) -> Dataset:
    """Populate snapshot_uri and stats for a dataset, returning the refreshed dataset."""
    filters = dataset.filters or {}
    stmt = (
        sa.select(Chunk)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.project_id == dataset.project_id)
        .order_by(Chunk.document_id, Chunk.order)
    )
    doc_ids = filters.get("doc_ids")
    if doc_ids:
        stmt = stmt.where(Chunk.document_id.in_(doc_ids))

    rows: list[Chunk] = db.scalars(stmt).all()
    buf = io.StringIO()
    chars = 0
    docs: set[str] = set()
    for row in rows:
        payload = {
            "doc_id": row.document_id,
            "chunk_id": row.id,
            "order": row.order,
            "content": row.content,
            "metadata": row.meta,
        }
        if isinstance(row.content, dict) and row.content.get("type") == "text":
            chars += len(row.content.get("text", ""))
        docs.add(str(row.document_id))
        buf.write(json.dumps(payload) + "\n")

    key = dataset_snapshot_key(str(dataset.id))
    store.put_bytes(key, buf.getvalue().encode("utf-8"))
    dataset.snapshot_uri = key
    dataset.stats = {"rows": len(rows), "chars": chars, "docs": len(docs)}
    db.commit()
    db.refresh(dataset)
    return dataset
