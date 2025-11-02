from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Iterable, Optional, Tuple

from core.settings import get_settings
from services.ocr import run_ocr
from storage.object_store import ObjectStore, derived_key

logger = logging.getLogger(__name__)

METRICS = {"hits": 0, "misses": 0, "time": 0.0}


def _lang_list(langs: str) -> Iterable[str]:
    parts = [chunk.strip() for chunk in langs.replace(",", "+").split("+")]
    return [p for p in parts if p]


def _cache_key(doc_id: str, page_hash: str, langs: str, dpi: int) -> str:
    settings = get_settings()
    backend = (settings.ocr_backend or "tesseract").lower()
    if backend == "deepseek" and not settings.feature_deepseek_ocr:
        backend = "paddle"
    runtime = settings.deepseek_ocr_runtime if backend == "deepseek" else "na"
    return derived_key(
        doc_id,
        f"ocr_cache/{page_hash}_{langs}_{dpi}_{backend}_{runtime}.json",
    )


def ocr_cached(
    store: ObjectStore,
    doc_id: str,
    page_bytes: bytes,
    *,
    langs: str,
    dpi: int,
) -> Tuple[str, Optional[float]]:
    """OCR a page with caching based on content hash."""
    page_hash = hashlib.sha256(page_bytes).hexdigest()
    key = _cache_key(doc_id, page_hash, langs, dpi)
    try:
        payload = json.loads(store.get_bytes(key).decode("utf-8"))
        METRICS["hits"] += 1
        return payload["text"], payload.get("conf")
    except Exception:
        METRICS["misses"] += 1
        start = time.perf_counter()
        try:
            result = run_ocr(page_bytes, mode="text", langs=_lang_list(langs))
            text = (result.get("text") or result.get("md") or "").strip()
            meta = result.get("meta") or {}
            conf = meta.get("confidence")
            conf_mean = float(conf) if isinstance(conf, (int, float)) else None
        except Exception as exc:  # pragma: no cover - fallback logging
            logger.warning("OCR cache miss failed: %s", exc)
            text, conf_mean = "", None
        METRICS["time"] += time.perf_counter() - start
        store.put_bytes(
            key, json.dumps({"text": text, "conf": conf_mean}).encode("utf-8")
        )
        return text, conf_mean


def cache_hit_ratio() -> float:
    total = METRICS["hits"] + METRICS["misses"]
    return METRICS["hits"] / total if total else 0.0


def ocr_time() -> float:
    return METRICS["time"]


__all__ = ["ocr_cached", "cache_hit_ratio", "ocr_time", "METRICS"]
