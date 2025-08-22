from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Iterable, Iterator, List

from core.hash import stable_chunk_key


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).lower()


def _token_count(text: str) -> int:
    return len(text.split())


@dataclass
class Block:
    text: str
    type: str = "text"  # "text", "table_placeholder", or "table_text"
    page: int | None = None
    section_path: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


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


def _hash_text(content: ChunkContent, section_path: List[str]) -> str:
    text = (
        content.text
        if content.type in {"text", "table_text"} and content.text
        else content.type
    )
    normalized = _normalize_text(text)
    return stable_chunk_key(section_path, normalized)


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
    current_meta: dict | None = None

    def flush() -> None:
        nonlocal buf, current_tokens, start_page, current_section, chunks, current_meta
        if not buf:
            return
        text = "\n".join(buf).strip()
        content = ChunkContent(type="text", text=text)
        text_hash = _hash_text(content, current_section)
        chunk = Chunk(
            id=uuid.uuid5(uuid.NAMESPACE_URL, text_hash),
            order=len(chunks),
            content=content,
            source=ChunkSource(page=start_page, section_path=current_section.copy()),
            text_hash=text_hash,
            metadata=current_meta.copy() if current_meta else {},
        )
        chunks.append(chunk)
        buf = []
        current_tokens = 0
        start_page = None
        current_section = []
        current_meta = None

    for block in blocks:
        if block.type == "table_placeholder":
            flush()
            content = ChunkContent(type="table_placeholder", text=None)
            text_hash = _hash_text(content, block.section_path)
            chunks.append(
                Chunk(
                    id=uuid.uuid5(uuid.NAMESPACE_URL, text_hash),
                    order=len(chunks),
                    content=content,
                    source=ChunkSource(
                        page=block.page, section_path=block.section_path.copy()
                    ),
                    text_hash=text_hash,
                    metadata=block.metadata.copy(),
                )
            )
            continue
        if block.type == "table_text":
            flush()
            content = ChunkContent(type="table_text", text=block.text)
            text_hash = _hash_text(content, block.section_path)
            chunks.append(
                Chunk(
                    id=uuid.uuid5(uuid.NAMESPACE_URL, text_hash),
                    order=len(chunks),
                    content=content,
                    source=ChunkSource(
                        page=block.page, section_path=block.section_path.copy()
                    ),
                    text_hash=text_hash,
                    metadata=block.metadata.copy(),
                )
            )
            continue

        tokens = _token_count(block.text)
        if not buf:
            start_page = block.page
            current_section = block.section_path.copy()
            current_meta = block.metadata.copy()
        elif block.section_path != current_section or block.metadata != current_meta:
            flush()
            start_page = block.page
            current_section = block.section_path.copy()
            current_meta = block.metadata.copy()
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
