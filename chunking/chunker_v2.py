from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Iterable, List


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).lower()


def _token_count(text: str) -> int:
    return len(text.split())


@dataclass
class Block:
    text: str
    type: str = "text"  # "text", "table_placeholder", or "table_text"
    file_path: str | None = None
    page: int | None = None
    section_path: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class ChunkContent:
    type: str
    text: str | None = None


@dataclass
class Chunk:
    id: uuid.UUID
    order: int
    content: ChunkContent
    text_hash: str
    metadata: dict = field(default_factory=dict)
    rev: int = 1


def _hash_text(content: ChunkContent) -> str:
    text = (
        content.text
        if content.type in {"text", "table_text"} and content.text
        else content.type
    )
    return hashlib.sha256(_normalize_text(text).encode("utf-8")).hexdigest()


def chunk_blocks(blocks: Iterable[Block], *, max_tokens: int = 900) -> List[Chunk]:
    chunks: List[Chunk] = []
    buf: List[str] = []
    current_tokens = 0
    start_page: int | None = None
    current_section: List[str] = []
    current_file: str | None = None
    current_step: int | None = None
    next_step = 1

    def flush() -> None:
        nonlocal buf, current_tokens, start_page, current_section, current_file, current_step
        if not buf:
            return
        text = "\n".join(buf).strip()
        content = ChunkContent(type="text", text=text)
        text_hash = _hash_text(content)
        chunks.append(
            Chunk(
                id=uuid.uuid5(uuid.NAMESPACE_URL, text_hash),
                order=len(chunks),
                content=content,
                text_hash=text_hash,
                metadata={
                    "file_path": current_file,
                    "page": start_page,
                    "section_path": current_section.copy(),
                    **({"step_id": current_step} if current_step is not None else {}),
                },
            )
        )
        buf = []
        current_tokens = 0
        start_page = None
        current_section = []
        current_file = None

    for block in blocks:
        if block.type == "table_placeholder":
            flush()
            content = ChunkContent(type="table_placeholder", text=None)
            text_hash = _hash_text(content)
            chunks.append(
                Chunk(
                    id=uuid.uuid5(uuid.NAMESPACE_URL, text_hash),
                    order=len(chunks),
                    content=content,
                    text_hash=text_hash,
                    metadata={
                        "file_path": block.file_path,
                        "page": block.page,
                        "section_path": block.section_path.copy(),
                        **block.metadata,
                        **(
                            {"step_id": current_step}
                            if current_step is not None
                            else {}
                        ),
                    },
                )
            )
            continue

        if block.type == "table_text":
            flush()
            lines = block.text.splitlines()
            tbuf: List[str] = []
            tokens = 0
            for line in lines:
                line_tokens = _token_count(line)
                if tbuf and tokens + line_tokens > max_tokens:
                    text = "\n".join(tbuf).strip()
                    content = ChunkContent(type="table_text", text=text)
                    text_hash = _hash_text(content)
                    chunks.append(
                        Chunk(
                            id=uuid.uuid5(uuid.NAMESPACE_URL, text_hash),
                            order=len(chunks),
                            content=content,
                            text_hash=text_hash,
                            metadata={
                                "file_path": block.file_path,
                                "page": block.page,
                                "section_path": block.section_path.copy(),
                                **block.metadata,
                                **(
                                    {"step_id": current_step}
                                    if current_step is not None
                                    else {}
                                ),
                            },
                        )
                    )
                    tbuf = []
                    tokens = 0
                tbuf.append(line)
                tokens += line_tokens
            if tbuf:
                text = "\n".join(tbuf).strip()
                content = ChunkContent(type="table_text", text=text)
                text_hash = _hash_text(content)
                chunks.append(
                    Chunk(
                        id=uuid.uuid5(uuid.NAMESPACE_URL, text_hash),
                        order=len(chunks),
                        content=content,
                        text_hash=text_hash,
                        metadata={
                            "file_path": block.file_path,
                            "page": block.page,
                            "section_path": block.section_path.copy(),
                            **block.metadata,
                            **(
                                {"step_id": current_step}
                                if current_step is not None
                                else {}
                            ),
                        },
                    )
                )
            continue

        if block.file_path != current_file:
            flush()
            current_step = None
        if block.metadata.get("kind") == "title":
            flush()
            current_step = None
        if block.metadata.get("kind") == "step":
            flush()
            current_step = next_step
            next_step += 1

        tokens = _token_count(block.text)
        if not buf:
            start_page = block.page
            current_section = block.section_path.copy()
            current_file = block.file_path
        buf.append(block.text)
        current_tokens += tokens
        if current_tokens >= max_tokens:
            flush()

    flush()
    return chunks


__all__ = ["Block", "Chunk", "ChunkContent", "chunk_blocks"]
