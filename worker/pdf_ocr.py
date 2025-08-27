from __future__ import annotations

import io
import logging
from typing import Iterable

try:
    import pytesseract  # type: ignore[import-untyped]
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    pytesseract = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]

from worker.ocr.config import tesseract_lang_string

logger = logging.getLogger(__name__)


def ocr_page(pixmap_bytes: bytes, langs: Iterable[str]) -> str:
    """OCR a PDF page represented by pixmap bytes.

    Args:
        pixmap_bytes: Raw image bytes from ``fitz.Pixmap.tobytes``.
        langs: Iterable of Tesseract language codes.
    Returns:
        Extracted text or an empty string on failure or when pytesseract is
        unavailable.
    """
    if pytesseract is None or Image is None:
        logger.warning("pytesseract not installed; OCR skipped")
        return ""
    try:
        img = Image.open(io.BytesIO(pixmap_bytes))
    except Exception:  # pragma: no cover - best effort
        return ""
    lang_str = tesseract_lang_string(langs)
    try:
        data = pytesseract.image_to_data(
            img, lang=lang_str, output_type=pytesseract.Output.DICT
        )
    except Exception as exc:  # pragma: no cover - tesseract missing
        logger.warning("pytesseract OCR failed: %s", exc)
        return ""
    words = [w.strip() for w in data.get("text", []) if w.strip()]
    return " ".join(words)


__all__ = ["ocr_page"]
