import io
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

import fitz  # type: ignore[import-not-found, import-untyped]
import pytesseract  # type: ignore[import-untyped]
from PIL import Image

from storage.object_store import ObjectStore
from worker.ocr_cache import ocr_cached


@dataclass
class Block:
    text: str
    kind: str
    meta: Dict[str, object] = field(default_factory=dict)


@dataclass
class PageMetrics:
    page: int
    ocr_used: bool
    ocr_conf_mean: Optional[float]


class PDFParserV2:
    def __init__(self, *, lang: str = "eng") -> None:
        self.lang = lang
        self.page_metrics: List[PageMetrics] = []

    def parse(
        self,
        data: bytes,
        *,
        doc_id: str | None = None,
        store: ObjectStore | None = None,
    ) -> Iterator[Block]:
        doc = fitz.open(stream=data, filetype="pdf")
        for page_index, page in enumerate(doc, start=1):
            pdf_text = page.get_text("text")
            text_len = len(pdf_text.strip())
            image_count = len(page.get_images(full=True))

            ocr_used = False
            ocr_conf_mean: Optional[float] = None
            ocr_text = ""
            if text_len < 50 and image_count > 0:
                ocr_text, ocr_conf_mean = self._ocr_page(
                    page, doc_id=doc_id, store=store
                )
                ocr_used = True

            self.page_metrics.append(
                PageMetrics(
                    page=page_index, ocr_used=ocr_used, ocr_conf_mean=ocr_conf_mean
                )
            )

            for line in pdf_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                kind = "title" if line.isupper() else "text"
                yield Block(
                    text=line,
                    kind=kind,
                    meta={"page": page_index, "source_stage": "pdf_text"},
                )

            if ocr_used:
                for line in ocr_text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    kind = "title" if line.isupper() else "text"
                    yield Block(
                        text=line,
                        kind=kind,
                        meta={"page": page_index, "source_stage": "pdf_ocr"},
                    )

    def _ocr_page(
        self,
        page: fitz.Page,
        *,
        doc_id: str | None,
        store: ObjectStore | None,
    ) -> tuple[str, Optional[float]]:
        pix = page.get_pixmap(dpi=300)
        page_bytes = pix.tobytes("png")
        if doc_id is not None and store is not None:
            return ocr_cached(store, doc_id, page_bytes, langs=self.lang, dpi=300)
        img = Image.open(io.BytesIO(page_bytes))
        data = pytesseract.image_to_data(
            img, lang=self.lang, output_type=pytesseract.Output.DICT
        )
        words = [w.strip() for w in data["text"] if w.strip()]
        confs = [float(c) for c in data["conf"] if c not in {"-1", ""}]
        text = " ".join(words)
        conf_mean = sum(confs) / len(confs) if confs else None
        return text, conf_mean


__all__ = ["Block", "PageMetrics", "PDFParserV2"]
