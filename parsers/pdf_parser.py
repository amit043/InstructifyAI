from __future__ import annotations

import io
import uuid as _uuid
from typing import List, Tuple

import fitz  # type: ignore[import-not-found, import-untyped]

from core.hash import sha256_bytes, sha256_str
from storage.object_store import ObjectStore, figure_key, put_image_bytes
from text.normalize import normalize_text
from worker.pdf_ocr import ocr_page


def _norm_bbox(bbox: list[float] | tuple[float, float, float, float], w: float, h: float) -> list[float]:
    try:
        x0, y0, x1, y1 = map(float, bbox)
        return [
            max(0.0, min(1.0, x0 / w)) if w else 0.0,
            max(0.0, min(1.0, y0 / h)) if h else 0.0,
            max(0.0, min(1.0, x1 / w)) if w else 0.0,
            max(0.0, min(1.0, y1 / h)) if h else 0.0,
        ]
    except Exception:
        return [0.0, 0.0, 0.0, 0.0]


def parse_pdf(
    doc_id: str,
    version: int,
    raw_pdf_bytes: bytes,
    store: ObjectStore,
    settings,
) -> Tuple[List[dict], dict]:
    """
    Parse a PDF combining native text and image OCR.

    - Emits text chunks from native PDF text (source_stage=pdf_text)
    - Emits image chunks for each image region with OCR text (source_stage=image_ocr)
    - If page text coverage is low, OCR full page and emit additional text (source_stage=pdf_ocr)

    Returns rows and metrics.
    """
    pdf = fitz.open(stream=raw_pdf_bytes, filetype="pdf")
    rows: List[dict] = []
    order = 0
    pages_ocr: set[int] = set()
    images_total = 0
    images_ocr_non_empty = 0

    ocr_langs = list(getattr(settings, "ocr_langs", []) or []) or ["eng"]
    min_text_len_for_ocr = int(getattr(settings, "min_text_len_for_ocr", 0) or 0)

    for page_index, page in enumerate(pdf, start=1):
        rect = page.rect
        width, height = float(rect.width), float(rect.height)

        # Native page text
        native_text = page.get_text("text") or ""
        native_norm = normalize_text(native_text)
        if native_norm:
            rows.append(
                {
                    # id computed deterministically in upsert
                    "document_id": doc_id,
                    "version": version,
                    "order": order,
                    "content": {"type": "text", "text": native_norm},
                    "text": native_norm,
                    "text_hash": sha256_str(native_norm),
                    "meta": {
                        "content_type": "text",
                        "source_stage": "pdf_text",
                        "page": page_index,
                        "section_path": [],
                    },
                }
            )
            order += 1

        # Image regions via raw dict
        raw = page.get_text("rawdict") or {}
        blocks = raw.get("blocks", []) if isinstance(raw, dict) else []
        img_i = 0
        for blk in blocks:
            if not isinstance(blk, dict) or blk.get("type") != 1:
                continue
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
            images_total += 1
            img_i += 1
            # OCR the image crop
            ocr_text = ocr_page(img_bytes, ocr_langs) or ""
            if ocr_text.strip():
                images_ocr_non_empty += 1

            # Save image in derived figures and reference by key
            filename = f"p{page_index}_{img_i}.png"
            key = put_image_bytes(store, doc_id, filename, img_bytes)

            rows.append(
                {
                    "document_id": doc_id,
                    "version": version,
                    "order": order,
                    "content": {
                        "type": "image",
                        "image_key": key,  # signed later
                        "ocr_text": ocr_text,
                    },
                    "text": None,
                    "text_hash": sha256_str(ocr_text) if ocr_text else sha256_bytes(img_bytes),
                    "meta": {
                        "content_type": "image",
                        "source_stage": "image_ocr",
                        "page": page_index,
                        "section_path": [],
                        "bbox": _norm_bbox(bbox, width, height),
                    },
                }
            )
            order += 1

        # Page-level OCR fallback if native text poor
        if len(native_norm.strip()) < min_text_len_for_ocr:
            try:
                pix = page.get_pixmap(dpi=300)
                page_png = pix.tobytes("png")
                page_ocr = normalize_text(ocr_page(page_png, ocr_langs) or "")
            except Exception:
                page_ocr = ""
            if page_ocr:
                pages_ocr.add(page_index)
                rows.append(
                    {
                        "document_id": doc_id,
                        "version": version,
                        "order": order,
                        "content": {"type": "text", "text": page_ocr},
                        "text": page_ocr,
                        "text_hash": sha256_str(page_ocr),
                        "meta": {
                            "content_type": "text",
                            "source_stage": "pdf_ocr",
                            "page": page_index,
                            "section_path": [],
                        },
                    }
                )
                order += 1

    pdf.close()

    metrics = {
        "pages_ocr": sorted(pages_ocr),
        "image_count": images_total,
        "image_ocr_ratio": (images_ocr_non_empty / images_total) if images_total else 0.0,
    }
    return rows, metrics


__all__ = ["parse_pdf"]

