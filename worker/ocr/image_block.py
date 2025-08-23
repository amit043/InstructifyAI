from __future__ import annotations

from io import BytesIO
from typing import Tuple

import pytesseract  # type: ignore[import-untyped]
from PIL import Image  # type: ignore[import-untyped]


def ocr_image_block(image_bytes: bytes, *, langs: str = "eng") -> Tuple[str, float]:
    """OCR text from an image block and return text and mean confidence."""
    image = Image.open(BytesIO(image_bytes))
    data = pytesseract.image_to_data(
        image, lang=langs, output_type=pytesseract.Output.DICT
    )
    text = " ".join(data.get("text", [])).strip()
    confs = [float(c) for c in data.get("conf", []) if c != "-1"]
    conf_mean = sum(confs) / len(confs) if confs else 0.0
    return text, conf_mean


__all__ = ["ocr_image_block"]
