from __future__ import annotations

import json
from typing import Any, Dict, Iterable

from datasets import Dataset


def _iter_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def build_pref_dataset(*, input_path: str) -> Dataset:
    """Build preference dataset with (prompt, chosen, rejected).

    Accepts JSONL where each line is one of:
    - {"prompt": str, "chosen": str, "rejected": str}
    - {"instruction": str, "input": str, "accepted": str, "alternative": str}
    Falls back to skipping lines that don't provide both variants.
    """
    prompt, chosen, rejected = [], [], []
    for rec in _iter_jsonl(input_path):
        p = rec.get("prompt")
        c = rec.get("chosen")
        r = rec.get("rejected")
        if p is None:
            instr = rec.get("instruction")
            ipt = rec.get("input")
            if instr is not None:
                p = f"Instruction:\n{instr}\n\nInput:\n{ipt or ''}".strip()
            c = c or rec.get("accepted")
            r = r or rec.get("alternative")
        if not (p and c and r):
            continue
        prompt.append(str(p))
        chosen.append(str(c))
        rejected.append(str(r))

    if not prompt:
        raise ValueError("no preference examples available")

    return Dataset.from_dict({"prompt": prompt, "chosen": chosen, "rejected": rejected})

