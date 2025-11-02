from __future__ import annotations

import logging
import io
from typing import Iterable, Optional

try:
    import pytesseract  # type: ignore[import-untyped]
    from PIL import Image
except Exception:  # pragma: no cover
    pytesseract = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]

from services.ocr.base import OCRResult, OCRRunner, OCRUnavailableError
from worker.ocr.config import tesseract_lang_string

logger = logging.getLogger(__name__)


class TesseractOCRRunner(OCRRunner):
    backend_name = "tesseract"

    def run(
        self,
        image_bytes: bytes,
        *,
        mode: str = "text",
        langs: Optional[Iterable[str]] = None,
        **_: object,
    ) -> OCRResult:
        if pytesseract is None or Image is None:  # pragma: no cover
            raise OCRUnavailableError("pytesseract not installed")
        lang_str = tesseract_lang_string(langs or ["eng"])
        image = Image.open(io.BytesIO(image_bytes))
        data = pytesseract.image_to_data(
            image, lang=lang_str, output_type=pytesseract.Output.DICT
        )
        words = [w.strip() for w in data.get("text", []) if w.strip()]
        text = " ".join(words)
        meta = {"backend": self.backend_name, "mode": mode, "langs": lang_str}
        return OCRResult(
            text=text,
            md=text if mode == "markdown" else None,
            meta=meta,
            ctx_compressed=self._compress(text),
        )


__all__ = ["TesseractOCRRunner"]
