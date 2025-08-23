"""Tesseract OCR configuration helpers."""

from __future__ import annotations

from typing import Iterable, List


def tesseract_lang_string(langs: Iterable[str]) -> str:
    """Join languages for Tesseract OCR.

    Ensures deterministic order and removes duplicates.
    """
    ordered: List[str] = []
    for lang in langs:
        if lang not in ordered:
            ordered.append(lang)
    return "+".join(ordered) if ordered else "eng"


__all__ = ["tesseract_lang_string"]
