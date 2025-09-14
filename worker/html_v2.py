from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from typing import Iterator, Tuple

import bs4
from sqlalchemy.orm import Session

from models import Document, DocumentVersion
from storage.object_store import ObjectStore, figure_key, raw_bundle_key, raw_key
from text.normalize import chunk_by_tokens, normalize_text, simhash64
from worker.pdf_ocr import ocr_page


def _sha256(s: bytes | str) -> str:
    if isinstance(s, str):
        s = s.encode("utf-8")
    return hashlib.sha256(s).hexdigest()


def _clean_html(html: str) -> bs4.BeautifulSoup:
    soup = bs4.BeautifulSoup(html, "lxml")
    for tag in soup(
        ["script", "style", "noscript", "svg", "nav", "aside", "footer", "form"]
    ):
        tag.decompose()
    for el in soup.find_all(True, {"class": ["header", "footer", "nav", "cookie"]}):
        el.decompose()
    return soup


def _iter_sections(soup: bs4.BeautifulSoup) -> Iterator[tuple[list[str], str]]:
    section: list[str] = []
    for el in soup.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "code"]
    ):
        if el.name and el.name.startswith("h"):
            level = int(el.name[1])
            title = normalize_text(el.get_text(" "))
            if title:
                section = section[: level - 1] + [title]
        else:
            text = normalize_text(el.get_text(" "))
            if text:
                yield section[:], text


def parse_html_v2(
    db: Session,
    store: ObjectStore,
    doc: Document,
    dv: DocumentVersion,
    *,
    settings: dict | None = None,
    parser_overrides: dict | None = None,
    job_id: str | None = None,
    source_hint: dict | None = None,
) -> Tuple[list[dict], dict, dict, dict[str, list[dict[str, str]]]]:
    """
    Parse HTML (single|zip|crawl) with de-boilerplate, heading-aware chunking, and optional image OCR.
    """
    _ = db, parser_overrides, job_id
    cfg = settings or {}
    download_images = bool(cfg.get("download_images", True))
    max_image_bytes = int(cfg.get("max_image_bytes", 2_000_000) or 2_000_000)
    target_tokens = int(cfg.get("chunk_token_target", 1200) or 1200)
    overlap_tokens = int(cfg.get("chunk_token_overlap", 200) or 200)
    ocr_langs = list(cfg.get("ocr_langs", [])) or ["eng"]

    mode_zip = (
        bool(source_hint and source_hint.get("zip")) or dv.mime == "application/zip"
    )
    mode_crawl = dv.mime == "application/x-crawl" or bool(
        source_hint and source_hint.get("base_url")
    )

    def emit_for_html(
        html: str, file_path: str | None, start_order: int
    ) -> tuple[list[dict], dict, int]:
        soup = _clean_html(html)
        rows: list[dict] = []
        order = start_order
        # Text by sections
        buffer: list[str] = []
        current_section: list[str] = []
        for sect, text in _iter_sections(soup):
            if sect != current_section and buffer:
                joined = "\n".join(buffer)
                for part in chunk_by_tokens(joined, target_tokens, overlap_tokens):
                    part_norm = normalize_text(part)
                    rows.append(
                        {
                            "id": _sha256(f"{doc.id}:{file_path}:{order}:{part_norm}"),
                            "document_id": doc.id,
                            "version": dv.version,
                            "order": order,
                            "content": {"type": "text", "text": part_norm},
                            "text": part_norm,
                            "text_hash": _sha256(part_norm),
                            "meta": {
                                "content_type": "text",
                                "source_stage": "html_text",
                                "page": None,
                                "section_path": current_section,
                                "file_path": file_path,
                            },
                            "rev": 1,
                        }
                    )
                    order += 1
                buffer = []
            current_section = sect
            buffer.append(text)
        if buffer:
            joined = "\n".join(buffer)
            for part in chunk_by_tokens(joined, target_tokens, overlap_tokens):
                part_norm = normalize_text(part)
                rows.append(
                    {
                        "id": _sha256(f"{doc.id}:{file_path}:{order}:{part_norm}"),
                        "document_id": doc.id,
                        "version": dv.version,
                        "order": order,
                        "content": {"type": "text", "text": part_norm},
                        "text": part_norm,
                        "text_hash": _sha256(part_norm),
                        "meta": {
                            "content_type": "text",
                            "source_stage": "html_text",
                            "page": None,
                            "section_path": current_section,
                            "file_path": file_path,
                        },
                        "rev": 1,
                    }
                )
                order += 1

        # Images
        image_count = 0
        for i, img in enumerate(soup.find_all("img"), start=1):
            src = img.get("src")
            if not src:
                continue
            img_bytes: bytes | None = None
            if src.startswith("data:image/"):
                try:
                    header, b64 = src.split(",", 1)
                    import base64

                    img_bytes = base64.b64decode(b64)
                except Exception:
                    img_bytes = None
            elif download_images:
                # best effort: skip external fetch in tests; only handle local zip path
                img_bytes = None
            if not img_bytes:
                continue
            if len(img_bytes) > max_image_bytes:
                continue
            image_count += 1
            # store
            img_name = f"{(file_path or 'html')}-{i}.png".replace(os.sep, "_")
            key = figure_key(doc.id, img_name)
            store.put_bytes(key, img_bytes)
            ocr_text = ocr_page(img_bytes, ocr_langs)
            rows.append(
                {
                    "id": _sha256(f"{doc.id}:{file_path}:img{i}"),
                    "document_id": doc.id,
                    "version": dv.version,
                    "order": order,
                    "content": {
                        "type": "image",
                        "image_url": key,
                        "bbox": None,
                        "ocr_text": ocr_text or "",
                    },
                    "text": None,
                    "text_hash": _sha256(ocr_text) if ocr_text else _sha256(img_bytes),
                    "meta": {
                        "content_type": "image",
                        "source_stage": "image_ocr",
                        "page": None,
                        "section_path": current_section,
                        "file_path": file_path,
                    },
                    "rev": 1,
                }
            )
            order += 1
        metrics = {"image_count": image_count}
        return rows, metrics, order

    rows: list[dict] = []
    metrics: dict = {"image_count": 0}
    artifacts: dict = {}
    order_counter = 0

    if mode_zip:
        data = store.get_bytes(raw_bundle_key(doc.id))
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            html_files = [
                n for n in zf.namelist() if n.lower().endswith((".html", ".htm"))
            ]
            seen_hashes: list[int] = []
            for name in html_files:
                content = zf.read(name).decode("utf-8", errors="ignore")
                soup = _clean_html(content)
                page_text = normalize_text(soup.get_text(" "))
                h = simhash64(page_text)
                if any(bin(h ^ s).count("1") <= 3 for s in seen_hashes):
                    metrics["duplicates_removed"] = (
                        metrics.get("duplicates_removed", 0) + 1
                    )
                    continue
                seen_hashes.append(h)
                rws, m, order_counter = emit_for_html(content, name, order_counter)
                rows.extend(rws)
                metrics["image_count"] += m.get("image_count", 0)
            metrics["file_count"] = len(html_files)
    elif mode_crawl:
        index = json.loads(
            store.get_bytes(raw_key(doc.id, "crawl/crawl_index.json")).decode("utf-8")
        )
        seen_hashes: list[int] = []
        crawled_urls: list[str] = []
        for url, content in index.items():
            soup = _clean_html(content)
            page_text = normalize_text(soup.get_text(" "))
            h = simhash64(page_text)
            if any(bin(h ^ s).count("1") <= 3 for s in seen_hashes):
                metrics["duplicates_removed"] = metrics.get("duplicates_removed", 0) + 1
                continue
            seen_hashes.append(h)
            crawled_urls.append(url)
            rws, m, order_counter = emit_for_html(content, url, order_counter)
            rows.extend(rws)
            metrics["image_count"] += m.get("image_count", 0)
        metrics["pages_crawled"] = len(crawled_urls)
        metrics["crawled_urls"] = crawled_urls
    else:
        filename = dv.meta.get("filename")
        if not isinstance(filename, str):
            raise RuntimeError("filename missing")
        html = store.get_bytes(raw_key(doc.id, filename)).decode(
            "utf-8", errors="ignore"
        )
        rws, m, order_counter = emit_for_html(html, filename, order_counter)
        rows.extend(rws)
        metrics["image_count"] += m.get("image_count", 0)

    meta_patch = {"parse": {}}
    redactions: dict[str, list[dict[str, str]]] = {}
    return rows, metrics, meta_patch, redactions


__all__ = ["parse_html_v2"]
