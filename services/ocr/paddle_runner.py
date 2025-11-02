from __future__ import annotations

import io
import logging
from typing import Iterable, Optional

import numpy as np
from PIL import Image

from services.ocr.base import OCRResult, OCRRunner, OCRUnavailableError

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional heavy dependency
    from paddleocr import PaddleOCR  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    PaddleOCR = None  # type: ignore[assignment]


class PaddleOCRRunner(OCRRunner):
    backend_name = "paddle"

    def __init__(self) -> None:
        self._clients: dict[str, "PaddleOCR"] = {}

    def _client_for_lang(self, langs: Iterable[str] | None) -> "PaddleOCR":
        lang = next(iter(langs or ["en"])).split("_")[0]
        if PaddleOCR is None:
            raise OCRUnavailableError("paddleocr is not installed")
        if lang not in self._clients:
            use_gpu = _gpu_available()
            logger.info(
                "Initializing PaddleOCR (lang=%s, use_gpu=%s)", lang, use_gpu
            )
            self._clients[lang] = PaddleOCR(
                lang=lang, use_angle_cls=True, use_gpu=use_gpu
            )
        return self._clients[lang]

    def run(
        self,
        image_bytes: bytes,
        *,
        mode: str = "text",
        langs: Optional[Iterable[str]] = None,
        **_: object,
    ) -> OCRResult:
        client = self._client_for_lang(langs)
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        result = client.ocr(np.array(image), cls=True)
        texts: list[str] = []
        for block in result:
            for _, (text, _) in block:
                if text:
                    texts.append(text)
        text_joined = "\n".join(texts).strip()
        meta = {
            "backend": self.backend_name,
            "mode": mode,
            "lang": next(iter(langs or ["en"])),
        }
        return OCRResult(
            text=text_joined if mode == "text" else "",
            md=text_joined if mode == "markdown" else None,
            meta=meta,
            ctx_compressed=self._compress(text_joined),
        )


def _gpu_available() -> bool:
    try:  # pragma: no cover
        import paddle

        return bool(getattr(paddle, "is_compiled_with_cuda", lambda: False)())
    except Exception:
        return False


__all__ = ["PaddleOCRRunner"]
