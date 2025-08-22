import random
from collections import defaultdict
from typing import Dict, List, Tuple


def apply_split(chunks: List[dict], spec: Dict) -> Tuple[List[dict], Dict[str, int]]:
    strategy = spec.get("strategy")
    if strategy != "stratified":
        raise ValueError("unsupported split strategy")
    by = spec.get("by") or []
    seed = spec.get("seed")
    fractions = spec.get("fractions", {"train": 0.8, "test": 0.2})
    rnd = random.Random(seed)
    docs: Dict[str, List[dict]] = defaultdict(list)
    meta_vals: Dict[str, Tuple] = {}
    for ch in chunks:
        docs[ch["doc_id"]].append(ch)
        meta = ch.get("metadata", {})
        key = tuple(meta.get(f) for f in by)
        meta_vals[ch["doc_id"]] = key
    groups: Dict[Tuple, List[str]] = defaultdict(list)
    for doc_id, key in meta_vals.items():
        groups[key].append(doc_id)
    doc_split: Dict[str, str] = {}
    for key, doc_ids in groups.items():
        rnd.shuffle(doc_ids)
        n = len(doc_ids)
        items = list(fractions.items())
        start = 0
        for i, (name, frac) in enumerate(items):
            count = int(round(frac * n))
            if i == len(items) - 1:
                count = n - start
            for doc_id in doc_ids[start : start + count]:
                doc_split[doc_id] = name
            start += count
    counts = {name: 0 for name in fractions.keys()}
    default_split = next(iter(fractions.keys()))
    for doc_id, chs in docs.items():
        split_name = doc_split.get(doc_id, default_split)
        for ch in chs:
            meta = ch.setdefault("metadata", {})
            meta["split"] = split_name
            counts[split_name] += 1
    return chunks, counts
