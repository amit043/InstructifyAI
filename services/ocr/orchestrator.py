from __future__ import annotations

import logging
from typing import Iterable, Literal, Optional

from core.settings import get_settings
from observability.metrics import OCR_FALLBACK_TOTAL
from services.ocr.base import OCRResult, OCRRunner, OCRUnavailableError
from services.ocr.deepseek_runner import DeepseekOCRRunner
from services.ocr.paddle_runner import PaddleOCRRunner
from services.ocr.tesseract_runner import TesseractOCRRunner

logger = logging.getLogger(__name__)

_deepseek_runner: DeepseekOCRRunner | None = None
_paddle_runner: PaddleOCRRunner | None = None
_tesseract_runner: TesseractOCRRunner | None = None


def reset_ocr_runners() -> None:
    global _deepseek_runner, _paddle_runner, _tesseract_runner
    _deepseek_runner = None
    _paddle_runner = None
    _tesseract_runner = None


def run_ocr(
    image_bytes: bytes,
    *,
    mode: Literal["text", "markdown"] = "text",
    langs: Optional[Iterable[str]] = None,
) -> dict:
    """Run OCR using configured backend with fallbacks."""
    settings = get_settings()
    langs = list(langs or ["eng"])
    backend = (settings.ocr_backend or "tesseract").lower()

    if backend == "deepseek" and settings.feature_deepseek_ocr:
        try:
            return _ensure_deepseek(settings).run(
                image_bytes, mode=mode, langs=langs
            ).as_dict()
        except OCRUnavailableError as exc:
            logger.warning("DeepSeek OCR unavailable: %s", exc)
            _record_fallback("deepseek", "paddle")
            backend = "paddle"
        except Exception as exc:
            logger.exception("DeepSeek OCR failed: %s", exc)
            _record_fallback("deepseek", "paddle")
            backend = "paddle"
    elif backend == "deepseek":
        logger.info(
            "DeepSeek OCR requested but FEATURE_DEEPSEEK_OCR=false; falling back to Paddle"
        )
        backend = "paddle"

    if backend == "paddle":
        try:
            return _ensure_paddle().run(
                image_bytes, mode=mode, langs=langs
            ).as_dict()
        except OCRUnavailableError as exc:
            logger.warning("PaddleOCR unavailable: %s", exc)
            _record_fallback("paddle", "tesseract")
        except Exception as exc:
            logger.exception("PaddleOCR failed: %s", exc)
            _record_fallback("paddle", "tesseract")

    return _ensure_tesseract().run(
        image_bytes, mode=mode, langs=langs
    ).as_dict()


def _ensure_deepseek(settings) -> DeepseekOCRRunner:
    global _deepseek_runner
    if _deepseek_runner is None:
        _deepseek_runner = DeepseekOCRRunner(
            model=settings.deepseek_ocr_model,
            runtime=settings.deepseek_ocr_runtime,
        )
    return _deepseek_runner


def _ensure_paddle() -> PaddleOCRRunner:
    global _paddle_runner
    if _paddle_runner is None:
        _paddle_runner = PaddleOCRRunner()
    return _paddle_runner


def _ensure_tesseract() -> TesseractOCRRunner:
    global _tesseract_runner
    if _tesseract_runner is None:
        _tesseract_runner = TesseractOCRRunner()
    return _tesseract_runner


def _record_fallback(src: str, dst: str) -> None:
    try:
        OCR_FALLBACK_TOTAL.labels(src, dst).inc()
    except Exception:  # pragma: no cover
        logger.debug("Failed to bump OCR fallback metric", exc_info=True)


__all__ = ["run_ocr", "reset_ocr_runners"]
