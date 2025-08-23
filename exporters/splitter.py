import random
from collections import defaultdict
from typing import Dict, List, Tuple, Union

from .common import SplitSpec


def _get_field(ch: dict, field: str):
    """Fetch a field from chunk root, metadata, or source."""

    if field in ch:
        return ch[field]
    meta = ch.get("metadata", {})
    if field in meta:
        return meta[field]
    src = ch.get("source", {})
    return src.get(field)


def apply_split(
    chunks: List[dict], spec: Union[Dict, SplitSpec]
) -> Tuple[List[dict], Dict[str, int]]:
    if isinstance(spec, dict):
        spec = SplitSpec(**spec)
    if spec.strategy != "stratified":
        raise ValueError("unsupported split strategy")
    rnd = random.Random(spec.seed)
    docs: Dict[str, List[dict]] = defaultdict(list)
    meta_vals: Dict[str, Tuple] = {}
    for ch in chunks:
        docs[ch["doc_id"]].append(ch)
        key = tuple(_get_field(ch, f) for f in spec.by)
        meta_vals[ch["doc_id"]] = key
    groups: Dict[Tuple, List[str]] = defaultdict(list)
    for doc_id, key in meta_vals.items():
        groups[key].append(doc_id)
    doc_split: Dict[str, str] = {}
    for key, doc_ids in groups.items():
        rnd.shuffle(doc_ids)
        n = len(doc_ids)
        items = list(spec.fractions.items())
        start = 0
        for i, (name, frac) in enumerate(items):
            if i == len(items) - 1:
                end = n
            else:
                end = start + int(round(frac * n))
            for doc_id in doc_ids[start:end]:
                doc_split[doc_id] = name
            start = end
    counts = {name: 0 for name in spec.fractions.keys()}
    default_split = next(iter(spec.fractions.keys()))
    for doc_id, chs in docs.items():
        split_name = doc_split.get(doc_id, default_split)
        for ch in chs:
            meta = ch.setdefault("metadata", {})
            meta["split"] = split_name
            counts[split_name] += 1
    total = sum(counts.values())
    if total:
        for name, frac in spec.fractions.items():
            actual = counts[name] / total
            if abs(actual - frac) > spec.tolerance:
                raise ValueError("split fractions outside tolerance")
    return chunks, counts
