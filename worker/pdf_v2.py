from __future__ import annotations

import hashlib
import uuid as _uuid
from typing import Tuple

import fitz  # type: ignore[import-not-found, import-untyped]
from sqlalchemy.orm import Session

from models import Document, DocumentVersion
from parser_pipeline.metrics import char_coverage
from storage.object_store import ObjectStore, figure_key, raw_key
from text.normalize import chunk_by_tokens, normalize_text
from worker.pdf_ocr import ocr_page


def _sha256(s: bytes | str) -> str:
    if isinstance(s, str):
        s = s.encode("utf-8")
    return hashlib.sha256(s).hexdigest()


def parse_pdf_v2(
    db: Session,
    store: ObjectStore,
    doc: Document,
    dv: DocumentVersion,
    *,
    settings: dict | None = None,
    parser_overrides: dict | None = None,
    job_id: str | None = None,
) -> Tuple[list[dict], dict, dict, dict[str, list[dict[str, str]]]]:
    """
    Parse PDF combining native text with per-image OCR and page OCR fallback.
    Emits both text and image chunks. Returns rows, metrics, meta_patch, redactions.
    """
    _ = db, job_id
    cfg = settings or {}
    ocr_langs = list(cfg.get("ocr_langs", [])) or ["eng"]
    min_text_len_for_ocr = int(cfg.get("min_text_len_for_ocr", 50) or 50)
    download_images = bool(cfg.get("download_images", True))
    max_image_bytes = int(cfg.get("max_image_bytes", 2_000_000) or 2_000_000)
    target_tokens = int(cfg.get("chunk_token_target", 1200) or 1200)
    overlap_tokens = int(cfg.get("chunk_token_overlap", 200) or 200)

    filename = dv.meta.get("filename")
    if not isinstance(filename, str):
        raise RuntimeError("filename missing")
    data = store.get_bytes(raw_key(doc.id, filename))

    pdf = fitz.open(stream=data, filetype="pdf")

    rows: list[dict] = []
    order = 0
    pages_ocr: set[int] = set()
    page_langs: dict[int, str] = {}
    page_images: dict[int, int] = {}
    images_ocr_non_empty = 0
    images_total = 0
    artifacts_files: list[str] = []

    for page_index, page in enumerate(pdf, start=1):
        rect = page.rect
        width, height = float(rect.width), float(rect.height)
        native_text = page.get_text("text") or ""
        native_text_norm = normalize_text(native_text)
        cov = char_coverage(native_text_norm)
        coverage_ratio = cov["ascii_ratio"] + cov["latin1_ratio"]

        # Image blocks with bbox
        raw = page.get_text("rawdict") or {}
        blocks = raw.get("blocks", []) if isinstance(raw, dict) else []
        img_i = 0
        for blk in blocks:
            if not isinstance(blk, dict) or blk.get("type") != 1:
                continue
            img_i += 1
            bbox = blk.get("bbox") or [0, 0, 0, 0]
            image_info = blk.get("image") or {}
            xref = image_info.get("xref") if isinstance(image_info, dict) else None
            if not xref:
                continue
            try:
                pix = fitz.Pixmap(pdf, int(xref))
                img_bytes = pix.tobytes("png")
            except Exception:
                continue
            if len(img_bytes) > max_image_bytes:
                continue
            images_total += 1
            ocr_text = ocr_page(img_bytes, ocr_langs)
            if ocr_text.strip():
                images_ocr_non_empty += 1

            # Store image
            if download_images:
                img_name = f"page-{page_index}-{img_i}.png"
                key = figure_key(doc.id, img_name)
                store.put_bytes(key, img_bytes)
                artifacts_files.append(key)
                image_ref = key
            else:
                image_ref = f"inline:page-{page_index}-{img_i}"

            # Normalize bbox to 0..1
            try:
                x0, y0, x1, y1 = map(float, bbox)
                nb = {
                    "x": max(0.0, min(1.0, x0 / width)) if width else 0.0,
                    "y": max(0.0, min(1.0, y0 / height)) if height else 0.0,
                    "w": max(0.0, min(1.0, (x1 - x0) / width)) if width else 0.0,
                    "h": max(0.0, min(1.0, (y1 - y0) / height)) if height else 0.0,
                }
            except Exception:
                nb = {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}

            chunk_id = str(
                _uuid.uuid5(_uuid.NAMESPACE_URL, f"{doc.id}/p{page_index}-img{img_i}")
            )
            content = {
                "type": "image",
                "image_url": image_ref,
                "bbox": nb,
                "ocr_text": ocr_text or "",
            }
            rows.append(
                {
                    "id": chunk_id,
                    "document_id": doc.id,
                    "version": dv.version,
                    "order": order,
                    "content": content,
                    "text": None,
                    "text_hash": _sha256(ocr_text) if ocr_text else _sha256(img_bytes),
                    "meta": {
                        "content_type": "image",
                        "source_stage": "image_ocr",
                        "page": page_index,
                        "section_path": [],
                        "file_path": image_ref if download_images else None,
                    },
                    "rev": 1,
                }
            )
            order += 1
            page_images[page_index] = page_images.get(page_index, 0) + 1

        # Page-level OCR fallback
        page_text = native_text_norm
        if len(page_text) < min_text_len_for_ocr or coverage_ratio < 0.5:
            try:
                pix = page.get_pixmap(dpi=300)
                page_png = pix.tobytes("png")
                ocr_txt = normalize_text(ocr_page(page_png, ocr_langs))
            except Exception:
                ocr_txt = ""
            if ocr_txt:
                pages_ocr.add(page_index)
                page_text = (page_text + "\n" + ocr_txt).strip()

        # Language guess per page (based on combined text)
        if page_text:
            # best-effort: rely on coverage meta; we do not import langdetect here to keep deps minimal
            pass

        # Chunk text for this page
        if page_text:
            chunks = chunk_by_tokens(page_text, target_tokens, overlap_tokens)
            for txt in chunks:
                txt_norm = normalize_text(txt)
                rows.append(
                    {
                        "id": str(
                            _uuid.uuid5(
                                _uuid.NAMESPACE_URL,
                                f"{doc.id}/p{page_index}-t{order}",
                            )
                        ),
                        "document_id": doc.id,
                        "version": dv.version,
                        "order": order,
                        "content": {"type": "text", "text": txt_norm},
                        "text": txt_norm,
                        "text_hash": _sha256(txt_norm),
                        "meta": {
                            "content_type": "text",
                            "source_stage": (
                                "pdf_text"
                                if page_index not in pages_ocr
                                else "pdf_text"
                            ),
                            "page": page_index,
                            "section_path": [],
                        },
                        "rev": 1,
                    }
                )
                order += 1

    pdf.close()

    # Metrics / meta patch
    metrics = {
        "image_count": images_total,
        "image_ocr_ratio": (
            (images_ocr_non_empty / images_total) if images_total else 0.0
        ),
        "pages_ocr": sorted(pages_ocr),
        "page_images": page_images,
    }
    meta_patch = {"parse": {"pages_ocr": sorted(pages_ocr)}}
    redactions: dict[str, list[dict[str, str]]] = {}

    return rows, metrics, meta_patch, redactions


__all__ = ["parse_pdf_v2"]
