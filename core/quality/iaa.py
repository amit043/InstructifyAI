from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Audit, Chunk


def audit_action_with_conflict(
    db: Session,
    chunk_id: str,
    user: str,
    base_action: str,
    before: dict,
    after: dict,
) -> str:
    """Return action with `_conflict` suffix if other annotators disagree."""
    changes = {k: after[k] for k in after if before.get(k) != after[k]}
    if not changes:
        return base_action
    existing = (
        db.query(Audit).filter(Audit.chunk_id == chunk_id, Audit.user != user).all()
    )
    for audit in existing:
        prev = audit.after or {}
        for field, value in changes.items():
            if field in prev and prev[field] != value:
                return f"{base_action}_conflict"
    return base_action


def _cohen_kappa(pairs: Iterable[Tuple[str, str]]) -> float:
    data = list(pairs)
    total = len(data)
    if total == 0:
        return 0.0
    agree = sum(1 for a, b in data if a == b)
    counts1 = Counter(a for a, _ in data)
    counts2 = Counter(b for _, b in data)
    categories = set(counts1) | set(counts2)
    expected = sum(
        (counts1.get(cat, 0) / total) * (counts2.get(cat, 0) / total)
        for cat in categories
    )
    po = agree / total
    if expected == 1:
        return 1.0
    return (po - expected) / (1 - expected)


def compute_iaa(doc_id: str, version: int, db: Session) -> Dict[str, float]:
    """Compute Cohen's κ per field for a document version."""
    stmt = (
        select(Audit, Chunk)
        .join(Chunk, Audit.chunk_id == Chunk.id)
        .where(Chunk.document_id == doc_id, Chunk.version == version)
        .order_by(Audit.created_at)
    )
    rows = db.execute(stmt).all()
    annotations: dict[str, dict[str, Dict[str, str]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for audit, chunk in rows:
        before = audit.before or {}
        after = audit.after or {}
        changes = {k: after[k] for k in after if before.get(k) != after[k]}
        if not changes:
            continue
        for field, value in changes.items():
            annotations[chunk.id][field][audit.user] = value
    field_pairs: dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for chunk_fields in annotations.values():
        for field, user_vals in chunk_fields.items():
            if len(user_vals) >= 2:
                users = list(user_vals)
                field_pairs[field].append((user_vals[users[0]], user_vals[users[1]]))
    return {field: _cohen_kappa(pairs) for field, pairs in field_pairs.items()}
