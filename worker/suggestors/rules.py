from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Dict


@dataclass
class Suggestion:
    field: str
    value: str
    confidence: float
    rationale: str
    span: str

    def to_dict(self) -> Dict[str, str | float]:
        return asdict(self)


_SEVERITY_RE = re.compile(r"\b(DEBUG|INFO|WARN|ERROR|FATAL)\b")
_STEP_RE = re.compile(r"\bStep\s?\d+:?")
_TICKET_RE = re.compile(r"\b(?:JIRA|BUG|INC)-\d+\b")
_DATETIME_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?\b")


def suggest(text: str) -> Dict[str, Dict[str, str | float]]:
    suggestions: Dict[str, Suggestion] = {}
    if m := _SEVERITY_RE.search(text):
        val = m.group(1)
        suggestions["severity"] = Suggestion(
            field="severity",
            value=val,
            confidence=0.9,
            rationale="regex match",
            span=m.group(0),
        )
    if m := _STEP_RE.search(text):
        val = m.group(0).strip()
        suggestions["step_id"] = Suggestion(
            field="step_id",
            value=val,
            confidence=0.9,
            rationale="regex match",
            span=m.group(0),
        )
    if m := _TICKET_RE.search(text):
        val = m.group(0)
        suggestions["ticket_id"] = Suggestion(
            field="ticket_id",
            value=val,
            confidence=0.9,
            rationale="regex match",
            span=val,
        )
    if m := _DATETIME_RE.search(text):
        val = m.group(0)
        suggestions["datetime"] = Suggestion(
            field="datetime",
            value=val,
            confidence=0.9,
            rationale="regex match",
            span=val,
        )
    return {k: v.to_dict() for k, v in suggestions.items()}
