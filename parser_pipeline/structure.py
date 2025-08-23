from __future__ import annotations

import re
import statistics
from typing import Iterator, List

from chunking.chunker import Block

try:  # optional deps in some environments
    import fitz  # type: ignore[import-not-found, import-untyped]
except Exception:  # pragma: no cover - handled via importorskip in tests
    fitz = None  # type: ignore

try:
    from bs4 import BeautifulSoup, NavigableString, Tag  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - handled via importorskip in tests
    BeautifulSoup = NavigableString = Tag = None  # type: ignore


def _html_blocks(data: bytes) -> Iterator[Block]:
    soup = BeautifulSoup(data, "html.parser")
    for tag in soup.find_all(["nav", "footer", "aside"]):
        tag.decompose()
    stack: List[str] = []

    def traverse(node) -> Iterator[Block]:
        for child in node.children:
            if isinstance(child, NavigableString):
                text = str(child).strip()
                if text:
                    yield Block(text=text, section_path=stack.copy())
            elif isinstance(child, Tag):
                name = child.name.lower()
                if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                    level = int(name[1])
                    text = child.get_text(" ", strip=True)
                    stack[:] = stack[: level - 1]
                    stack.append(text)
                    yield Block(
                        text=text,
                        section_path=stack.copy(),
                        metadata={"kind": "title"},
                    )
                elif name == "table":
                    yield Block(
                        text="",
                        type="table_placeholder",
                        section_path=stack.copy(),
                    )
                elif name == "pre":
                    text = child.get_text("", strip=False)
                    if text:
                        yield Block(text=text, section_path=stack.copy())
                elif name == "li":
                    text = child.get_text(" ", strip=True)
                    if text:
                        yield Block(
                            text=text,
                            section_path=stack.copy(),
                            metadata={"kind": "step"},
                        )
                else:
                    yield from traverse(child)
        return

    body = soup.body or soup
    yield from traverse(body)


def _pdf_blocks(data: bytes) -> Iterator[Block]:
    if fitz is None:  # pragma: no cover - import guarded in tests
        raise RuntimeError("PyMuPDF not installed")
    doc = fitz.open(stream=data, filetype="pdf")
    for page_index, page in enumerate(doc, start=1):
        page_dict = page.get_text("dict")
        sizes: List[float] = []
        for blk in page_dict["blocks"]:
            if blk.get("type") != 0:
                continue
            for line in blk["lines"]:
                for span in line["spans"]:
                    sizes.append(span["size"])
        base = statistics.median(sizes) if sizes else 0
        current_section: List[str] = []
        first_line = True
        for blk in page_dict["blocks"]:
            if blk.get("type") != 0:
                continue
            block_text = "\n".join(
                "".join(span["text"] for span in line["spans"]) for line in blk["lines"]
            )
            if any(ch in block_text for ch in ("|", "\t")) or "  " in block_text:
                yield Block(
                    text="",
                    type="table_placeholder",
                    page=page_index,
                    section_path=current_section.copy(),
                )
                continue
            for line in blk["lines"]:
                spans = line["spans"]
                line_text = "".join(span["text"] for span in spans).strip()
                if not line_text:
                    continue
                line_size = max(span["size"] for span in spans)
                if line_size > base * 1.2 or (first_line and not current_section):
                    current_section = [line_text]
                    yield Block(
                        text=line_text,
                        page=page_index,
                        section_path=current_section.copy(),
                        metadata={"kind": "title"},
                    )
                elif re.match(
                    r"^(?:step\s*)?\d+[.)\s]", line_text, re.IGNORECASE
                ) or re.match(r"^[-*]\s+", line_text):
                    yield Block(
                        text=line_text,
                        page=page_index,
                        section_path=current_section.copy(),
                        metadata={"kind": "step"},
                    )
                else:
                    yield Block(
                        text=line_text,
                        page=page_index,
                        section_path=current_section.copy(),
                    )
                first_line = False


def structure(data: bytes, *, source_type: str) -> Iterator[Block]:
    if source_type == "text/html":
        yield from _html_blocks(data)
    elif source_type == "application/pdf":
        yield from _pdf_blocks(data)
    else:  # pragma: no cover - defensive
        raise ValueError(f"Unsupported source_type: {source_type}")


__all__ = ["structure"]
