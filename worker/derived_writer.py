from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Iterable, List, Tuple

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from chunking.chunker import Chunk
from core.settings import get_settings
from models import Chunk as ChunkModel
from storage.object_store import ObjectStore, derived_key, signed_url

# Curator-owned keys we want to preserve across re-parses
CURATED_KEYS = {"labels", "tags", "notes", "curated_fields"}
logger = logging.getLogger(__name__)


def _ensure_dict(v):
    if isinstance(v, dict) or v is None:
        return v or {}
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:  # pragma: no cover - best effort
            return {}
    return dict(v)


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


def migrate_metadata_rows(old: List[ChunkModel], rows: List[dict]) -> None:
    """
    Merge curator-owned metadata from previous rows into freshly parsed rows
    that have the same text_hash (content identity). Avoid clobbering new parse
    metadata like content_type/page/section_path/file_path/source_stage.
    Also carry over the existing revision counter.
    """
    by_hash = {c.text_hash: c for c in old}
    for row in rows:
        match = by_hash.get(row["text_hash"])
        if not match:
            continue
        legacy = match.meta or {}
        new_meta = dict(row.get("meta", {}))
        for k in CURATED_KEYS:
            if k in legacy:
                new_meta[k] = legacy[k]
        row["meta"] = new_meta
        # Keep existing rev; the UPSERT will bump on content change
        row["rev"] = getattr(match, "rev", row.get("rev", 1))


def write_chunks(store: ObjectStore, doc_id: str, rows: Iterable[dict]) -> None:
    key = derived_key(doc_id, "chunks.jsonl")
    lines: List[str] = []
    for row in rows:
        meta = _ensure_dict(row.get("meta", {}))
        # Allow richer content objects from v2 pipelines; fall back to legacy text-only
        if isinstance(row.get("content"), dict) and row["content"].get("type"):
            content_obj = _ensure_dict(row["content"])  # type: ignore[index]
        else:
            content_type = meta.get("content_type", "text")
            content_obj = {
                "type": content_type,
                **(
                    {"text": row.get("text")}
                    if row.get("text") is not None
                    and content_type != "table_placeholder"
                    else {}
                ),
            }

        payload = {
            "doc_id": doc_id,
            "chunk_id": row["id"],
            "order": row["order"],
            "rev": row.get("rev", 1),
            "content": content_obj,
            "source": {
                "page": meta.get("page"),
                "section_path": meta.get("section_path", []),
            },
            "text_hash": row["text_hash"],
            "metadata": meta,  # keep as native dict
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
    page_langs: List[str | None],
    langs_used: List[str],
    chunks: List[dict],
    deltas: dict[str, int],
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
        "stage_metrics": metrics or {},
        "files": files,
        "pages_ocr": pages_ocr,
        "page_langs": page_langs,
        "langs_used": langs_used,
        "chunks": chunks,
        "deltas": deltas,
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
    rows: List[dict] | None = None,
    chunks: List[Chunk] | None = None,
    metrics: dict | None = None,
) -> Tuple[str, str, dict[str, int]]:
    """
    Persist parsed chunk rows idempotently:
      - UPSERT by primary key (id) with rev bump only when text_hash changes
      - Delete rows that no longer exist for (document_id, version)
      - Write chunks.jsonl & manifest.json (with deltas computed by text_hash)
    Returns: (chunks_url, manifest_url, deltas)
    """
    # Normalize input to rows[]
    if rows is None and chunks is not None:
        rows = []
        for ch in chunks:
            meta = dict(ch.metadata)
            meta.setdefault("content_type", ch.content.type)
            meta.setdefault("page", ch.source.page)
            meta.setdefault("section_path", ch.source.section_path)
            rows.append(
                {
                    "id": str(ch.id),
                    "document_id": doc_id,
                    "version": version,
                    "order": ch.order,
                    "text": ch.content.text,
                    "text_hash": ch.text_hash,
                    "meta": meta,  # native dict for JSONB
                    "rev": ch.rev,
                }
            )
    assert rows is not None

    # --- Dedupe by ID (keep last occurrence) ---
    by_id = {}
    for r in rows:
        r["meta"] = _ensure_dict(r.get("meta"))
        by_id[r["id"]] = r
    if len(by_id) != len(rows):
        logger.warning("dropped %d duplicate rows", len(rows) - len(by_id))
        rows = list(by_id.values())
        rows.sort(key=lambda r: r["order"])

    # Merge curated metadata from existing rows (same content by text_hash)
    existing = (
        db.query(ChunkModel)
        .filter(ChunkModel.document_id == doc_id, ChunkModel.version == version)
        .all()
    )
    migrate_metadata_rows(existing, rows)

    # Build values for UPSERT (note: DB columns use "metadata" and "content")
    values = []
    for idx, row in enumerate(rows):
        meta = _ensure_dict(row.get("meta"))
        # Prefer provided content object if present and valid
        if isinstance(row.get("content"), dict) and row["content"].get("type"):
            content = _ensure_dict(row["content"])  # type: ignore[index]
        else:
            content = {
                "type": meta.get("content_type", "text"),
                **(
                    {"text": row.get("text")}
                    if row.get("text") is not None
                    and meta.get("content_type") != "table_placeholder"
                    else {}
                ),
            }
        # Ensure unique, monotonic order per document/version: reindex deterministically
        ord_val = idx

        values.append(
            {
                "id": row["id"],
                "document_id": doc_id,
                "version": version,
                "order": ord_val,
                "content": _ensure_dict(content),
                "text_hash": row["text_hash"],
                "metadata": _ensure_dict(meta),
                "rev": row.get("rev", 1),
            }
        )

    # UPSERT: bump rev only when text_hash changes
    stmt = insert(ChunkModel.__table__).values(values)  # type: ignore[arg-type]
    update_cols = {
        "document_id": stmt.excluded.document_id,
        "version": stmt.excluded.version,
        "order": stmt.excluded.order,
        "content": stmt.excluded.content,
        "text_hash": stmt.excluded.text_hash,
        "metadata": stmt.excluded["metadata"],
        "rev": sa.case(
            (
                ChunkModel.__table__.c.text_hash != stmt.excluded.text_hash,
                ChunkModel.__table__.c.rev + 1,
            ),
            else_=ChunkModel.__table__.c.rev,
        ),
    }
    if hasattr(ChunkModel, "updated_at"):
        update_cols["updated_at"] = sa.func.now()
    stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols)
    db.execute(stmt)

    # Final cleanup: delete rows not present in the new set for this doc/version
    new_ids = [row["id"] for row in rows]
    (
        db.query(ChunkModel)
        .filter(
            ChunkModel.document_id == doc_id,
            ChunkModel.version == version,
            ~ChunkModel.id.in_(new_ids),
        )
        .delete(synchronize_session=False)
    )

    # Commit DB writes before emitting artifacts (avoid partial rollback issues)
    db.commit()

    # ---- Artifacts: chunks.jsonl ----
    write_chunks(store, doc_id, rows)

    # ---- Manifest & deltas (by text_hash) ----
    files = sorted(
        {row["meta"].get("file_path") for row in rows if row["meta"].get("file_path")}
    )
    pages_ocr = sorted(
        {
            row["meta"].get("page")
            for row in rows
            if row["meta"].get("source_stage") == "pdf_ocr"
            and row["meta"].get("page") is not None
        }
    )
    # page -> lang map (first-seen)
    lang_pages: dict[int, str] = {}
    for row in rows:
        lang = row["meta"].get("lang")
        page = row["meta"].get("page")
        if lang and page is not None and page not in lang_pages:
            lang_pages[page] = lang
    langs_used = sorted(set(lang_pages.values()))
    max_page = max(lang_pages) if lang_pages else 0
    page_langs = [lang_pages.get(p) for p in range(1, max_page + 1)]

    # compute deltas vs previous manifest using text_hash
    manifest_key = derived_key(doc_id, "manifest.json")
    try:
        previous = json.loads(store.get_bytes(manifest_key).decode("utf-8"))
        prev_map = {c["order"]: c.get("text_hash") for c in previous.get("chunks", [])}
    except Exception:  # pragma: no cover
        prev_map = {}

    new_chunks = [
        {"id": row["id"], "order": row["order"], "text_hash": row["text_hash"]}
        for row in rows
    ]
    new_map = {c["order"]: c["text_hash"] for c in new_chunks}

    added = [o for o in new_map.keys() - prev_map.keys()]
    removed = [o for o in prev_map.keys() - new_map.keys()]
    changed = [o for o in new_map.keys() & prev_map.keys() if new_map[o] != prev_map[o]]
    deltas = {"added": len(added), "removed": len(removed), "changed": len(changed)}

    write_manifest(
        store,
        doc_id,
        files=files,
        metrics=metrics or {},
        pages_ocr=pages_ocr,
        page_langs=page_langs,
        langs_used=langs_used,
        chunks=new_chunks,
        deltas=deltas,
    )

    chunks_url = signed_url(store, derived_key(doc_id, "chunks.jsonl"))
    manifest_url = signed_url(store, manifest_key)
    return chunks_url, manifest_url, deltas
