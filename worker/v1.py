from __future__ import annotations

import logging
import subprocess
from typing import Any

import sqlalchemy as sa

try:  # optional dependency for PDFs
    import fitz  # type: ignore[import-not-found, import-untyped]
except Exception:  # pragma: no cover - fitz optional
    fitz = None  # type: ignore[assignment]

from chunking.chunker import Block, chunk_blocks
from core.lang_detect import detect_lang
from core.metrics import compute_parse_metrics
from core.pii import detect_pii
from core.settings import get_settings
from models import Document, DocumentVersion
from parser_pipeline.metrics import char_coverage
from parsers import registry
from storage.object_store import ObjectStore, raw_key
from worker.pdf_ocr import ocr_page
from worker.pipeline import get_parser_settings
from worker.suggestors import suggest

settings = get_settings()
logger = logging.getLogger(__name__)

try:
    version = subprocess.check_output(
        ["tesseract", "--version"], text=True
    ).splitlines()[0]
    TESSERACT_AVAILABLE = True
    logger.info("tesseract --version: %s", version)
except Exception as exc:  # noqa: BLE001
    TESSERACT_AVAILABLE = False
    logger.warning("tesseract --version failed: %s", exc)
    if settings.ocr_langs or settings.min_text_len_for_ocr:
        logger.warning("OCR configured but tesseract binary missing; OCR disabled")


def run_parse_v1(
    db: sa.orm.Session,
    store: ObjectStore,
    doc: Document,
    dv: DocumentVersion,
    parser_overrides: dict | None,
    stages: list[str] | None,
    reset_suggestions: bool,
) -> tuple[list[dict], dict, dict, dict[str, list[dict[str, str]]]]:
    _ = stages, reset_suggestions
    filename = dv.meta.get("filename")
    if not isinstance(filename, str):
        raise RuntimeError("filename missing")
    data = store.get_bytes(raw_key(doc.id, filename))
    parser_cls = registry.get(dv.mime)
    logger.info("Picked parser: %s for %s", parser_cls.__name__, dv.mime)
    try:
        blocks = list(parser_cls.parse(data, store=store, doc_id=doc.id))  # type: ignore[call-arg]
    except TypeError:
        blocks = list(parser_cls.parse(data))

    project = doc.project
    parser_settings = get_parser_settings(project)
    if parser_overrides:
        parser_settings.update(parser_overrides)

    chunk_size = None
    overlap = 0
    normalize = True
    if parser_overrides:
        chunk_size = parser_overrides.get("chunk_size")
        overlap = int(parser_overrides.get("overlap", 0))
        normalize = bool(parser_overrides.get("normalize", True))

    total_pages = 0
    if dv.mime == "application/pdf" and fitz is not None:
        pdf = fitz.open(stream=data, filetype="pdf")
        total_pages = pdf.page_count
        page_text: dict[int, str] = {}
        for b in blocks:
            b.metadata.setdefault("source_stage", "pdf_text")
            if b.page is not None:
                page_text.setdefault(b.page, "")
                page_text[b.page] += b.text + "\n"
        min_len = int(parser_settings.get("min_text_len_for_ocr", 0))
        ocr_langs = parser_settings.get("ocr_langs") or []
        for idx, page in enumerate(pdf, start=1):
            existing = page_text.get(idx, "")
            cov = char_coverage(existing)
            coverage_ratio = cov["ascii_ratio"] + cov["latin1_ratio"]
            if (
                (
                    len(existing.strip()) < min_len
                    or coverage_ratio < settings.text_coverage_threshold
                )
                and TESSERACT_AVAILABLE
                and ocr_langs
            ):
                pix = page.get_pixmap(dpi=300)
                ocr_text = ocr_page(pix.tobytes("png"), ocr_langs)
                if ocr_text.strip():
                    lang = detect_lang(ocr_text)
                    if lang:
                        for b in blocks:
                            if b.page == idx:
                                b.metadata.setdefault("lang", lang)
                        page_text[idx] = (
                            existing + ("\n" if existing else "") + ocr_text
                        )
                    else:
                        page_text[idx] = (
                            existing + ("\n" if existing else "") + ocr_text
                        )
                    for line in ocr_text.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        meta = {"source_stage": "pdf_ocr"}
                        if lang:
                            meta["lang"] = lang
                        blocks.append(
                            Block(text=line, page=idx, section_path=[], metadata=meta)
                        )
                else:
                    page_text[idx] = existing
            else:
                lang = detect_lang(existing)
                if lang:
                    for b in blocks:
                        if b.page == idx:
                            b.metadata.setdefault("lang", lang)
                page_text[idx] = existing
        extracted_text = "".join(
            page_text.get(p, "") for p in range(1, total_pages + 1)
        )
        pdf.close()
    else:
        for b in blocks:
            if dv.mime == "application/pdf":
                b.metadata.setdefault("source_stage", "pdf_text")
        extracted_text = "".join(b.text for b in blocks if getattr(b, "text", ""))

    if chunk_size:
        min_tokens = max(1, int(chunk_size) - int(overlap))
        chunks = chunk_blocks(
            blocks,
            min_tokens=min_tokens,
            max_tokens=int(chunk_size),
            normalize=normalize,
        )
    else:
        chunks = chunk_blocks(blocks, normalize=normalize)
    coverage = char_coverage(extracted_text)
    metrics = compute_parse_metrics(chunks, mime=dv.mime)
    metrics["text_coverage"] = coverage["ascii_ratio"] + coverage["latin1_ratio"]
    metrics["utf_other_ratio"] = coverage["other_ratio"]
    parse_meta: dict = {"char_coverage_extracted": coverage}
    meta_patch = {
        "metrics": metrics,
        "parser_settings": parser_settings,
        "parse": parse_meta,
    }

    if project.use_rules_suggestor or project.use_mini_llm:
        total = 0
        for ch in chunks:
            if ch.content.type != "text":
                continue
            remaining = (
                project.max_suggestions_per_doc or settings.max_suggestions_per_doc
            ) - total
            if remaining <= 0:
                break
            sugg = suggest(
                ch.content.text or "",
                use_rules_suggestor=project.use_rules_suggestor,
                use_mini_llm=project.use_mini_llm,
                max_suggestions=remaining,
                suggestion_timeout_ms=(
                    project.suggestion_timeout_ms or settings.suggestion_timeout_ms
                ),
            )
            if sugg:
                ch.metadata.setdefault("suggestions", {})
                for key, val in sugg.items():
                    ch.metadata["suggestions"][key] = val
                total += len(sugg)

    redactions: dict[str, list[dict[str, str]]] = {}
    total_pii = 0
    for ch in chunks:
        if ch.content.type != "text":
            continue
        matches = detect_pii(ch.content.text or "")
        if matches:
            ch.metadata.setdefault("suggestions", {})
            ch.metadata["suggestions"]["redactions"] = [
                {"type": m.type, "text": m.text} for m in matches
            ]
            redactions[str(ch.id)] = [{"type": m.type, "text": m.text} for m in matches]
            total_pii += len(matches)
    metrics["pii_count"] = total_pii

    rows = [
        {
            "id": str(ch.id),
            "document_id": doc.id,
            "version": dv.version,
            "order": ch.order,
            "text": ch.content.text,
            "text_hash": ch.text_hash,
            "meta": {
                **ch.metadata,
                "content_type": ch.content.type,
                "page": ch.source.page,
                "section_path": ch.source.section_path,
            },
        }
        for ch in chunks
    ]
    pages_ocr_final = {
        r["meta"].get("page")
        for r in rows
        if r["meta"].get("source_stage") == "pdf_ocr"
        and r["meta"].get("page") is not None
    }
    if total_pages:
        metrics["ocr_ratio"] = len(pages_ocr_final) / total_pages
    parse_meta["counts"] = {"chunks": len(rows)}
    return rows, metrics, meta_patch, redactions


__all__ = ["run_parse_v1"]
