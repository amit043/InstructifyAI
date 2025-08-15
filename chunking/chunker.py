from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Iterable, Iterator, List


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).lower()


def _token_count(text: str) -> int:
    return len(text.split())


@dataclass
class Block:
    text: str
    type: str = "text"  # "text" or "table_placeholder"
    page: int | None = None
    section_path: List[str] = field(default_factory=list)


@dataclass
class ChunkContent:
    type: str
    text: str | None = None


@dataclass
class ChunkSource:
    page: int | None = None
    section_path: List[str] = field(default_factory=list)


@dataclass
class Chunk:
    id: uuid.UUID
    order: int
    content: ChunkContent
    source: ChunkSource
    text_hash: str
    metadata: dict = field(default_factory=dict)
    rev: int = 1


def _hash_text(content: ChunkContent) -> str:
    text = content.text if content.type == "text" and content.text else content.type
    return hashlib.sha256(_normalize_text(text).encode("utf-8")).hexdigest()


def chunk_blocks(
    blocks: Iterable[Block],
    *,
    min_tokens: int = 700,
    max_tokens: int = 1000,
) -> List[Chunk]:
    chunks: List[Chunk] = []
    buf: List[str] = []
    current_tokens = 0
    start_page: int | None = None
    current_section: List[str] = []

    def flush() -> None:
        nonlocal buf, current_tokens, start_page, current_section, chunks
        if not buf:
            return
        text = "\n".join(buf).strip()
        content = ChunkContent(type="text", text=text)
        chunk = Chunk(
            id=uuid.uuid4(),
            order=len(chunks),
            content=content,
            source=ChunkSource(page=start_page, section_path=current_section.copy()),
            text_hash=_hash_text(content),
        )
        chunks.append(chunk)
        buf = []
        current_tokens = 0
        start_page = None
        current_section = []

    for block in blocks:
        if block.type == "table_placeholder":
            flush()
            content = ChunkContent(type="table_placeholder", text=None)
            chunks.append(
                Chunk(
                    id=uuid.uuid4(),
                    order=len(chunks),
                    content=content,
                    source=ChunkSource(
                        page=block.page, section_path=block.section_path.copy()
                    ),
                    text_hash=_hash_text(content),
                )
            )
            continue

        tokens = _token_count(block.text)
        if not buf:
            start_page = block.page
            current_section = block.section_path.copy()
        elif block.section_path != current_section and current_tokens >= min_tokens:
            flush()
            start_page = block.page
            current_section = block.section_path.copy()
        buf.append(block.text)
        current_tokens += tokens
        if current_tokens >= max_tokens:
            flush()

    flush()
    return chunks


__all__ = [
    "Block",
    "Chunk",
    "ChunkContent",
    "ChunkSource",
    "chunk_blocks",
]
