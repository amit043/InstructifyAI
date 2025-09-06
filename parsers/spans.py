import re
from dataclasses import dataclass
from typing import List


@dataclass
class Span:
    """Represents a detected span within text."""

    type: str
    start: int
    end: int
    text: str


_FENCE_RE = re.compile(r"(?P<fence>```|~~~)(.*?)(?P=fence)", re.DOTALL)
_INLINE_MATH_RE = re.compile(r"(?<!\\)\$(.+?)(?<!\\)\$")
_DISPLAY_MATH_RE = re.compile(
    r"\\\[(.+?)\\\]|(?<!\\)\$\$(.+?)(?<!\\)\$\$",
    re.DOTALL,
)


def _monospace_blocks(text: str) -> List[tuple[int, int]]:
    """Detect blocks that look like monospace code from PDFs.

    Heuristic: consecutive lines that start with at least four spaces or a tab
    are treated as a monospace block.
    """

    lines = text.splitlines(True)
    spans: List[tuple[int, int]] = []
    idx = 0
    block_start: int | None = None
    for line in lines:
        if re.match(r"^[ \t]{4,}", line):
            if block_start is None:
                block_start = idx
        else:
            if block_start is not None:
                spans.append((block_start, idx))
                block_start = None
        idx += len(line)
    if block_start is not None:
        spans.append((block_start, idx))
    return spans


def detect_spans(text: str) -> List[Span]:
    """Detect fenced code blocks, LaTeX math, and monospace spans."""

    spans: List[Span] = []
    for m in _FENCE_RE.finditer(text):
        spans.append(Span("code_fence", m.start(), m.end(), text[m.start() : m.end()]))
    for m in _DISPLAY_MATH_RE.finditer(text):
        spans.append(Span("math", m.start(), m.end(), text[m.start() : m.end()]))
    for m in _INLINE_MATH_RE.finditer(text):
        spans.append(Span("math", m.start(), m.end(), text[m.start() : m.end()]))
    for start, end in _monospace_blocks(text):
        spans.append(Span("monospace", start, end, text[start:end]))
    return sorted(spans, key=lambda s: s.start)


__all__ = ["Span", "detect_spans"]
