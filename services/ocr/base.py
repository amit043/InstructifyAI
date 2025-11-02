from __future__ import annotations

import base64
import io
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Optional

from PIL import Image


class OCRError(RuntimeError):
    """Base OCR error."""


class OCRUnavailableError(OCRError):
    """Raised when a backend cannot be used (missing deps, GPU, etc.)."""


class OCRRuntimeError(OCRError):
    """Raised when a backend fails after being selected."""


@dataclass
class OCRResult:
    text: str
    md: Optional[str]
    meta: dict[str, Any]
    ctx_compressed: Optional[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "md": self.md,
            "meta": self.meta,
            "ctx_compressed": self.ctx_compressed,
        }


class OCRRunner(ABC):
    """Interface for OCR backends."""

    backend_name = "base"

    @abstractmethod
    def run(
        self,
        image_bytes: bytes,
        *,
        mode: Literal["text", "markdown"] = "text",
        langs: Optional[Iterable[str]] = None,
        **opts: Any,
    ) -> OCRResult:
        raise NotImplementedError

    @staticmethod
    def _open_image(image_bytes: bytes) -> Image.Image:
        return Image.open(io.BytesIO(image_bytes)).convert("RGB")

    @staticmethod
    def _compress(text: str | None) -> str | None:
        if not text:
            return None
        data = zlib.compress(text.encode("utf-8"))
        return base64.urlsafe_b64encode(data).decode("ascii")
