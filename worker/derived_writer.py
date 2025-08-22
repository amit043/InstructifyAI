from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable, List, Tuple

from sqlalchemy.orm import Session

from chunking.chunker import Chunk
from core.settings import get_settings
from models import Chunk as ChunkModel
from storage.object_store import ObjectStore, derived_key, signed_url

try:  # pragma: no cover - best effort
    import fitz  # type: ignore[import-untyped]

    PYMUPDF_VERSION = getattr(fitz, "__doc__", "").split()[1].rstrip(":")
except Exception:  # pragma: no cover - import error
    PYMUPDF_VERSION = "unknown"

try:  # pragma: no cover - tesseract optional
    import pytesseract  # type: ignore[import-untyped]

    TESSERACT_VERSION = str(pytesseract.get_tesseract_version())
except Exception:  # pragma: no cover - not installed
    TESSERACT_VERSION = "unavailable"


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


def write_redactions(
    store: ObjectStore, doc_id: str, redactions: dict[str, list[dict[str, str]]]
) -> None:
    key = derived_key(doc_id, "redactions.jsonl")
    lines = [
        json.dumps({"chunk_id": cid, "redactions": reds})
        for cid, reds in redactions.items()
    ]
    payload = ("\n".join(lines) + "\n").encode("utf-8") if lines else b""
    store.put_bytes(key, payload)


def write_manifest(
    store: ObjectStore,
    doc_id: str,
    *,
    files: List[str],
    metrics: dict,
    pages_ocr: List[int],
    parts: dict[str, str] | None = None,
    deltas: dict[str, List[str]] | None = None,
) -> None:
    settings = get_settings()
    manifest = {
        "tool_versions": {
            "pymupdf": PYMUPDF_VERSION,
            "tesseract": TESSERACT_VERSION,
        },
        "thresholds": {
            "empty_chunk_ratio": settings.empty_chunk_ratio_threshold,
            "html_section_path_coverage": settings.html_section_path_coverage_threshold,
            "curation_completeness": settings.curation_completeness_threshold,
            "text_coverage": settings.text_coverage_threshold,
            "ocr_ratio": settings.ocr_ratio_threshold,
            "utf_other_ratio": settings.utf_other_ratio_threshold,
        },
        "stage_metrics": metrics,
        "files": files,
        "pages_ocr": pages_ocr,
        "parts": parts or {},
        "deltas": deltas or {"added": [], "removed": [], "changed": []},
        "created_at": datetime.utcnow().isoformat(),
    }
    key = derived_key(doc_id, "manifest.json")
    store.put_bytes(key, json.dumps(manifest, sort_keys=True).encode("utf-8"))


def upsert_chunks(
    db: Session,
    store: ObjectStore,
    *,
    doc_id: str,
    version: int,
    chunks: List[Chunk],
    metrics: dict | None = None,
    parts: dict[str, str] | None = None,
    deltas: dict[str, List[str]] | None = None,
) -> Tuple[str, str]:
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
    files = sorted(
        {ch.metadata["file_path"] for ch in chunks if "file_path" in ch.metadata}
    )
    pages_ocr = sorted(
        {
            ch.source.page
            for ch in chunks
            if ch.metadata.get("source_stage") == "pdf_ocr"
            and ch.source.page is not None
        }
    )
    write_manifest(
        store,
        doc_id,
        files=files,
        metrics=metrics or {},
        pages_ocr=pages_ocr,
        parts=parts,
        deltas=deltas,
    )
    chunks_url = signed_url(store, derived_key(doc_id, "chunks.jsonl"))
    manifest_url = signed_url(store, derived_key(doc_id, "manifest.json"))
    return chunks_url, manifest_url
