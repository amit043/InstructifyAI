from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any, Dict, List, Optional, Set

import numpy as np
import sqlalchemy as sa
from sqlalchemy.orm import Session

from core.settings import get_settings
from models.chunk import Chunk
from models.document import Document
from observability.metrics import GEN_EVIDENCE_RESULTS
from retrieval.embeddings import EmbeddingModel
from retrieval.index import VectorIndex

MAX_CANDIDATE_CHUNKS = 800
MIN_CHARS = 20
PROMPT_TOKEN_MIN_LEN = 3


@lru_cache()
def _embedding_model() -> EmbeddingModel:
    return EmbeddingModel()


def _collect_chunks(
    db: Session, project_id: str, document_id: Optional[str]
) -> List[Chunk]:
    stmt = sa.select(Chunk).order_by(Chunk.document_id, Chunk.order)
    if document_id:
        stmt = stmt.where(Chunk.document_id == document_id)
        stmt = stmt.limit(MAX_CANDIDATE_CHUNKS)
        rows = db.scalars(stmt).all()
        return list(rows)

    try:
        project_uuid = uuid.UUID(project_id)
    except Exception:
        return []

    stmt = (
        stmt.join(Document, Document.id == Chunk.document_id)
        .where(Document.project_id == project_uuid)
        .limit(MAX_CANDIDATE_CHUNKS)
    )
    rows = db.scalars(stmt).all()
    return list(rows)


def _normalize_chunk(chunk: Chunk) -> tuple[Optional[str], Dict[str, Any]]:
    content = chunk.content or {}
    text = content.get("text") or ""
    if not isinstance(text, str):
        text = ""
    text = text.strip()
    if not text:
        return None, {}

    section_path = content.get("section_path") or content.get("source", {}).get("section_path") or []
    if not isinstance(section_path, list):
        section_path = []

    meta: Dict[str, Any] = {
        "chunk_id": chunk.id,
        "doc_id": chunk.document_id,
        "order": chunk.order,
        "text": text,
        "section_path": section_path,
        "text_hash": chunk.text_hash,
    }
    return text, meta


def _tokenize_prompt(prompt: str) -> Set[str]:
    tokens = set()
    for raw in prompt.lower().split():
        cleaned = "".join(ch for ch in raw if ch.isalnum())
        if len(cleaned) >= PROMPT_TOKEN_MIN_LEN:
            tokens.add(cleaned)
    return tokens


def _keyword_overlap(tokens: Set[str], text: str) -> float:
    if not tokens:
        return 0.0
    text_tokens = set()
    for raw in text.lower().split():
        cleaned = "".join(ch for ch in raw if ch.isalnum())
        if len(cleaned) >= PROMPT_TOKEN_MIN_LEN:
            text_tokens.add(cleaned)
    if not text_tokens:
        return 0.0
    return len(tokens & text_tokens) / float(len(tokens))


def _compute_rank_score(
    meta: Dict[str, Any],
    similarity: float,
    document_id: Optional[str],
    prompt_tokens: Set[str],
) -> float:
    score = float(similarity)
    text = meta.get("text", "")
    if document_id and meta.get("doc_id") == document_id:
        score += 0.07
    section_path = meta.get("section_path") or []
    if isinstance(section_path, list):
        score += min(len(section_path) * 0.01, 0.05)
    overlap = _keyword_overlap(prompt_tokens, text)
    score += min(overlap * 0.2, 0.2)
    text_len_bonus = min(len(text) / 800.0, 0.1)
    score += text_len_bonus
    return score


def retrieve_evidence(
    db: Session,
    *,
    project_id: str,
    document_id: Optional[str],
    prompt: str,
    top_k: int | None = None,
) -> List[Dict[str, Any]]:
    """Return the top chunk candidates for grounding a response."""
    settings = get_settings()
    limit = top_k or settings.gen_evidence_top_k
    if limit <= 0:
        return []

    chunks = _collect_chunks(db, project_id, document_id)
    texts: List[str] = []
    metas: List[Dict[str, Any]] = []
    seen_hashes: Set[str] = set()
    for chunk in chunks:
        text, meta = _normalize_chunk(chunk)
        if text and len(text) >= MIN_CHARS:
            th = meta.get("text_hash")
            if th and th in seen_hashes:
                continue
            if th:
                seen_hashes.add(th)
            texts.append(text)
            metas.append(meta)

    if not texts:
        GEN_EVIDENCE_RESULTS.labels(result="empty").inc()
        return []

    model = _embedding_model()
    try:
        chunk_vectors = model.embed(texts).astype(np.float32)
        query_vec = model.embed([prompt]).astype(np.float32)
    except Exception:
        GEN_EVIDENCE_RESULTS.labels(result="error").inc()
        return []

    index = VectorIndex(chunk_vectors.shape[1])
    index.add(chunk_vectors, metas)
    raw_results = index.search(query_vec, top_k=max(limit * 3, limit))

    prompt_tokens = _tokenize_prompt(prompt)
    ranked: List[tuple[Dict[str, Any], float, float]] = []
    min_rank = settings.gen_min_rank_score or 0.0
    seen_chunks: Set[str] = set()
    for meta, sim_score in raw_results:
        chunk_id = meta.get("chunk_id")
        if not chunk_id or chunk_id in seen_chunks:
            continue
        detailed_score = _compute_rank_score(meta, sim_score, document_id, prompt_tokens)
        if detailed_score < min_rank:
            continue
        seen_chunks.add(chunk_id)
        ranked.append((meta, sim_score, detailed_score))

    ranked.sort(key=lambda item: item[2], reverse=True)

    evidence: List[Dict[str, Any]] = []
    for meta, sim_score, rank_score in ranked[:limit]:
        entry = dict(meta)
        entry["score"] = float(sim_score)
        entry["rank_score"] = float(rank_score)
        evidence.append(entry)

    GEN_EVIDENCE_RESULTS.labels(result="non_empty" if evidence else "empty").inc()
    return evidence


__all__ = ["retrieve_evidence"]
