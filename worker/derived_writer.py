from __future__ import annotations

import json
from typing import Iterable, List

from sqlalchemy.orm import Session

from chunking.chunker import Chunk
from models import Chunk as ChunkModel
from storage.object_store import ObjectStore, derived_key


def migrate_metadata(old: List[ChunkModel], new: List[Chunk]) -> None:
    by_hash = {c.text_hash: c for c in old}
    for chunk in new:
        match = by_hash.get(chunk.text_hash)
        if match:
            chunk.metadata = match.meta
            chunk.rev = match.rev


def write_chunks(store: ObjectStore, doc_id: str, chunks: Iterable[Chunk]) -> None:
    key = derived_key(doc_id, "chunks.jsonl")
    lines = []
    for ch in chunks:
        payload = {
            "doc_id": doc_id,
            "chunk_id": str(ch.id),
            "order": ch.order,
            "rev": ch.rev,
            "content": {
                "type": ch.content.type,
                **({"text": ch.content.text} if ch.content.text is not None else {}),
            },
            "source": {
                "page": ch.source.page,
                "section_path": ch.source.section_path,
            },
            "text_hash": ch.text_hash,
            "metadata": ch.metadata,
        }
        lines.append(json.dumps(payload, ensure_ascii=False))
    store.put_bytes(key, ("\n".join(lines) + "\n").encode("utf-8"))


def upsert_chunks(
    db: Session,
    store: ObjectStore,
    *,
    doc_id: str,
    version: int,
    chunks: List[Chunk],
) -> None:
    existing = (
        db.query(ChunkModel)
        .filter(ChunkModel.document_id == doc_id, ChunkModel.version == version)
        .all()
    )
    migrate_metadata(existing, chunks)
    db.query(ChunkModel).filter(
        ChunkModel.document_id == doc_id, ChunkModel.version == version
    ).delete()
    db.bulk_save_objects(
        [
            ChunkModel(
                id=str(ch.id),
                document_id=doc_id,
                version=version,
                order=ch.order,
                content={
                    "type": ch.content.type,
                    **(
                        {"text": ch.content.text} if ch.content.text is not None else {}
                    ),
                },
                text_hash=ch.text_hash,
                meta=ch.metadata,
                rev=ch.rev,
            )
            for ch in chunks
        ]
    )
    db.commit()
    write_chunks(store, doc_id, chunks)
