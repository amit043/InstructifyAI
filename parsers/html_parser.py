from __future__ import annotations

import os
import tempfile
import uuid
from collections import deque
from dataclasses import dataclass
from io import BytesIO
from typing import Iterable, List
from urllib.parse import urljoin, urlparse
from zipfile import ZipFile

import httpx
from bs4 import BeautifulSoup

from core.hash import stable_chunk_key


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).lower()


def _section_path_from_headings(soup: BeautifulSoup) -> List[List[str]]:
    """Walk the document and compute section path snapshots.

    Returns a list parallel to the yielded paragraphs indicating the current
    section path (h1..h6 hierarchy) for each paragraph encountered.
    """
    path: List[str] = []
    snapshots: List[List[str]] = []
    # Iterate through elements in document order
    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre"]):
        name = el.name or ""
        if name.startswith("h") and len(name) == 2 and name[1].isdigit():
            level = int(name[1])
            text = el.get_text(" ", strip=True)
            if not text:
                continue
            # shrink or extend path to this heading level
            if len(path) >= level:
                path = path[: level - 1]
            while len(path) < level - 1:
                path.append("")
            if len(path) == level - 1:
                path.append(text)
            else:
                path[level - 1] = text
            continue
        if name in {"p", "li", "pre"}:
            text = el.get_text(" ", strip=True)
            if text:
                snapshots.append(path.copy())
    return snapshots


def _extract_paragraphs(soup: BeautifulSoup) -> List[str]:
    paras: List[str] = []
    for el in soup.find_all(["p", "li", "pre"]):
        text = el.get_text(" ", strip=True)
        if text:
            paras.append(text)
    return paras


def _rows_from_html(html: bytes, *, base_meta: dict, start_order: int = 0) -> List[dict]:
    soup = BeautifulSoup(html, "html.parser")
    paras = _extract_paragraphs(soup)
    sec_paths = _section_path_from_headings(soup)
    rows: List[dict] = []
    for i, text in enumerate(paras):
        section_path = sec_paths[i] if i < len(sec_paths) else []
        key_text = _normalize_text(text)
        text_hash = stable_chunk_key(section_path, key_text)
        meta = {
            **base_meta,
            "content_type": "text",
            "section_path": section_path,
        }
        rows.append(
            {
                "order": start_order + i,
                "text": text,
                "text_hash": text_hash,
                "meta": meta,
            }
        )
    return rows


def parse_single(url: str, *, project_id: uuid.UUID) -> List[dict]:  # noqa: ARG001
    resp = httpx.get(url, follow_redirects=True)
    resp.raise_for_status()
    base_meta = {"url": url}
    return _rows_from_html(resp.content, base_meta=base_meta, start_order=0)


def parse_zip(zip_path: str, *, project_id: uuid.UUID) -> List[dict]:  # noqa: ARG001
    rows: List[dict] = []
    with ZipFile(zip_path) as zf:
        html_files = [f for f in zf.namelist() if f.lower().endswith(".html")]
        order = 0
        for name in html_files:
            with zf.open(name, "r") as fh:
                data = fh.read()
            base_meta = {"file_path": name}
            page_rows = _rows_from_html(data, base_meta=base_meta, start_order=order)
            rows.extend(page_rows)
            order += len(page_rows)
    return rows


def parse_dir(dir_path: str, *, project_id: uuid.UUID) -> List[dict]:  # noqa: ARG001
    rows: List[dict] = []
    order = 0
    for root, _dirs, files in os.walk(dir_path):
        for f in sorted(files):
            if not f.lower().endswith(".html"):
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, dir_path)
            with open(full, "rb") as fh:
                data = fh.read()
            base_meta = {"file_path": rel}
            page_rows = _rows_from_html(data, base_meta=base_meta, start_order=order)
            rows.extend(page_rows)
            order += len(page_rows)
    return rows


def crawl_from(
    base_url: str,
    max_depth: int,
    max_pages: int,
    *,
    project_id: uuid.UUID,  # noqa: ARG001
) -> List[dict]:
    visited: set[str] = set()
    q: deque[tuple[str, int]] = deque([(base_url, 0)])
    index: dict[str, str] = {}
    parsed_base = urlparse(base_url)
    host = parsed_base.netloc
    rows: List[dict] = []
    order = 0
    page_num = 0
    while q and len(index) < max_pages:
        url, depth = q.popleft()
        if url in visited or depth > max_depth:
            continue
        visited.add(url)
        try:
            resp = httpx.get(url, follow_redirects=True)
            if resp.status_code != 200 or "text/html" not in resp.headers.get(
                "content-type", ""
            ):
                continue
        except Exception:
            continue
        filename = f"page{page_num}.html"
        page_num += 1
        index[url] = filename
        base_meta = {"url": url, "file_path": filename}
        page_rows = _rows_from_html(resp.content, base_meta=base_meta, start_order=order)
        rows.extend(page_rows)
        order += len(page_rows)
        if depth < max_depth:
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                link = a.get("href")
                if not link:
                    continue
                nxt = urljoin(url, link)
                parsed = urlparse(nxt)
                if parsed.netloc != host:
                    continue
                if nxt not in visited and all(nxt != u for u, _ in q):
                    q.append((nxt, depth + 1))
    return rows


__all__ = [
    "parse_single",
    "parse_zip",
    "parse_dir",
    "crawl_from",
]

