from __future__ import annotations

from typing import Iterable, Tuple

from services.ocr import run_ocr


def _normalize_langs(langs: str) -> Iterable[str]:
    parts = [chunk.strip() for chunk in langs.replace(",", "+").split("+")]
    return [p for p in parts if p]


def ocr_image_block(image_bytes: bytes, *, langs: str = "eng") -> Tuple[str, float]:
    """OCR text from an image block and return text and mean confidence."""
    result = run_ocr(image_bytes, mode="text", langs=_normalize_langs(langs))
    text = (result.get("text") or result.get("md") or "").strip()
    meta = result.get("meta") or {}
    conf = meta.get("confidence")
    if isinstance(conf, (int, float)):
        conf_float = float(conf)
    else:
        conf_float = 0.0
    return text, conf_float


__all__ = ["ocr_image_block"]
