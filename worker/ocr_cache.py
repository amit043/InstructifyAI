from __future__ import annotations

import hashlib
import io
import json
import time
from typing import Optional, Tuple

import pytesseract  # type: ignore[import-untyped]
from PIL import Image

from storage.object_store import ObjectStore, derived_key

METRICS = {"hits": 0, "misses": 0, "time": 0.0}


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
    key = derived_key(doc_id, f"ocr_cache/{page_hash}_{langs}_{dpi}.json")
    try:
        payload = json.loads(store.get_bytes(key).decode("utf-8"))
        METRICS["hits"] += 1
        return payload["text"], payload.get("conf")
    except Exception:
        METRICS["misses"] += 1
        start = time.perf_counter()
        img = Image.open(io.BytesIO(page_bytes))
        data = pytesseract.image_to_data(
            img, lang=langs, output_type=pytesseract.Output.DICT
        )
        words = [w.strip() for w in data["text"] if w.strip()]
        confs = [float(c) for c in data["conf"] if c not in {"-1", ""}]
        text = " ".join(words)
        conf_mean = sum(confs) / len(confs) if confs else None
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
