from __future__ import annotations

import logging
from typing import Iterable

from services.ocr import run_ocr

logger = logging.getLogger(__name__)


def ocr_page(pixmap_bytes: bytes, langs: Iterable[str]) -> str:
    """OCR a PDF page represented by pixmap bytes.

    Args:
        pixmap_bytes: Raw image bytes from ``fitz.Pixmap.tobytes``.
        langs: Iterable of Tesseract language codes.
    Returns:
        Extracted text or an empty string when no backend succeeds.
    """
    try:
        result = run_ocr(pixmap_bytes, mode="text", langs=langs)
    except Exception as exc:  # pragma: no cover - best effort fallback
        logger.warning("OCR pipeline failed: %s", exc)
        return ""
    text = result.get("text") or ""
    if not text and result.get("md"):
        return result["md"] or ""
    return text


__all__ = ["ocr_page"]
