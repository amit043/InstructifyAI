import io
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

import fitz  # type: ignore[import-not-found, import-untyped]
import pytesseract  # type: ignore[import-untyped]
from PIL import Image

try:  # pragma: no cover - optional dependency
    from langdetect import (  # type: ignore[import-not-found, import-untyped]
        DetectorFactory,
        detect,
    )
except Exception:  # pragma: no cover - not installed
    DetectorFactory = None  # type: ignore[assignment]
    detect = None  # type: ignore[assignment]

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
    lang: str | None


class PDFParserV2:
    def __init__(self, *, langs: list[str] | None = None) -> None:
        self.langs = langs or ["eng"]
        self.page_metrics: List[PageMetrics] = []

    def parse(
        self,
        data: bytes,
        *,
        doc_id: str | None = None,
        store: ObjectStore | None = None,
    ) -> Iterator[Block]:
        if DetectorFactory:
            DetectorFactory.seed = 0
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
            combined = f"{pdf_text} {ocr_text}".strip()
            page_lang: str | None = None
            if combined and detect:
                try:
                    page_lang = detect(combined)
                except Exception:  # pragma: no cover - best effort
                    page_lang = None

            self.page_metrics.append(
                PageMetrics(
                    page=page_index,
                    ocr_used=ocr_used,
                    ocr_conf_mean=ocr_conf_mean,
                    lang=page_lang,
                )
            )

            for line in pdf_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                kind = "title" if line.isupper() else "text"
                meta = {"page": page_index, "source_stage": "pdf_text"}
                if page_lang:
                    meta["lang"] = page_lang
                yield Block(text=line, kind=kind, meta=meta)

            if ocr_used:
                for line in ocr_text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    kind = "title" if line.isupper() else "text"
                    meta = {"page": page_index, "source_stage": "pdf_ocr"}
                    if page_lang:
                        meta["lang"] = page_lang
                    yield Block(text=line, kind=kind, meta=meta)

    def _ocr_page(
        self,
        page: fitz.Page,
        *,
        doc_id: str | None,
        store: ObjectStore | None,
    ) -> tuple[str, Optional[float]]:
        pix = page.get_pixmap(dpi=300)
        page_bytes = pix.tobytes("png")
        langs = "+".join(self.langs)
        if doc_id is not None and store is not None:
            return ocr_cached(store, doc_id, page_bytes, langs=langs, dpi=300)
        img = Image.open(io.BytesIO(page_bytes))
        data = pytesseract.image_to_data(
            img, lang=langs, output_type=pytesseract.Output.DICT
        )
        words = [w.strip() for w in data["text"] if w.strip()]
        confs = [float(c) for c in data["conf"] if c not in {"-1", ""}]
        text = " ".join(words)
        conf_mean = sum(confs) / len(confs) if confs else None
        return text, conf_mean

    @property
    def langs_used(self) -> List[str]:
        return sorted({m.lang for m in self.page_metrics if m.lang})


__all__ = ["Block", "PageMetrics", "PDFParserV2"]
