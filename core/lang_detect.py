"""Language detection helpers."""

from __future__ import annotations

from typing import Iterable, List

try:  # optional dependency
    from langdetect import (  # type: ignore[import-not-found, import-untyped]
        DetectorFactory,
        detect,
    )
except Exception:  # pragma: no cover - langdetect optional
    DetectorFactory = None  # type: ignore[assignment]
    detect = None  # type: ignore[assignment]


TESSERACT_TO_ISO = {
    "eng": "en",
    "deu": "de",
    "fra": "fr",
    "spa": "es",
}


def detect_lang(text: str) -> str | None:
    """Detect language of given text using langdetect.

    Returns ISO-639-1 code or ``None`` when detection is unavailable.
    """
    if not text.strip() or detect is None or DetectorFactory is None:
        return None
    DetectorFactory.seed = 0
    try:
        return detect(text)
    except Exception:  # pragma: no cover - best effort
        return None


def tesseract_langs_to_iso(langs: Iterable[str]) -> List[str]:
    """Map Tesseract language codes (eng, deu) to ISO-639-1.

    Unknown codes are truncated to first two letters.
    """
    return [TESSERACT_TO_ISO.get(l, l[:2]) for l in langs]


def unknown_langs(langs_used: Iterable[str], ocr_langs: Iterable[str]) -> List[str]:
    """Return languages seen that are not in configured OCR langs."""
    allowed = set(tesseract_langs_to_iso(ocr_langs))
    return sorted({l for l in langs_used if l not in allowed})


__all__ = ["detect_lang", "tesseract_langs_to_iso", "unknown_langs"]
