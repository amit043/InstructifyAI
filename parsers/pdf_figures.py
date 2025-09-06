from __future__ import annotations

from dataclasses import dataclass
from typing import List

import fitz  # type: ignore[import-not-found, import-untyped]

from storage.object_store import ObjectStore, figure_key, signed_url


@dataclass
class PDFFigure:
    page: int
    image_key: str
    image_url: str
    caption: str | None


def extract_figures(
    pdf_bytes: bytes, *, store: ObjectStore, doc_id: str
) -> List[PDFFigure]:
    """Detect image blocks and nearby captions.

    For each image block, the image bytes are saved to the object store under a
    derived figures path. A presigned URL is returned along with a simple
    caption guess: the text of the next block if it is a text block.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    figures: List[PDFFigure] = []
    for page_index, page in enumerate(doc):
        blocks = page.get_text("dict").get("blocks", [])
        for i, block in enumerate(blocks):
            if block.get("type") != 1:
                continue
            img_bytes = block.get("image")
            if not isinstance(img_bytes, bytes):
                continue
            key = figure_key(doc_id, f"page{page_index}_img{i}.png")
            store.put_bytes(key, img_bytes)
            url = signed_url(store, key)
            caption: str | None = None
            for j in range(i + 1, len(blocks)):
                nb = blocks[j]
                if nb.get("type") == 0:
                    caption_lines = [
                        span["text"]
                        for line in nb.get("lines", [])
                        for span in line.get("spans", [])
                    ]
                    caption = "".join(caption_lines).strip() or None
                    break
            figures.append(
                PDFFigure(
                    page=page_index, image_key=key, image_url=url, caption=caption
                )
            )
    doc.close()
    return figures


__all__ = ["PDFFigure", "extract_figures"]
