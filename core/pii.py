from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


@dataclass
class PiiMatch:
    """Represents a PII occurrence in text."""

    type: str
    text: str


_EMAIL_RE = re.compile(r"\b[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b")
_ID_RE = re.compile(r"\bID\d{3,}\b")


def detect_pii(text: str) -> List[PiiMatch]:
    """Detect basic PII patterns in text."""

    matches: List[PiiMatch] = []
    for m in _EMAIL_RE.finditer(text):
        matches.append(PiiMatch(type="email", text=m.group(0)))
    for m in _PHONE_RE.finditer(text):
        matches.append(PiiMatch(type="phone", text=m.group(0)))
    for m in _ID_RE.finditer(text):
        matches.append(PiiMatch(type="id", text=m.group(0)))
    return matches


def redact_text(text: str, matches: List[PiiMatch]) -> str:
    """Replace detected PII spans with [REDACTED]."""

    for match in matches:
        text = text.replace(match.text, "[REDACTED]")
    return text


__all__ = ["detect_pii", "redact_text", "PiiMatch"]
