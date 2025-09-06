from __future__ import annotations

import json
from typing import Any, Dict, Iterable

from datasets import Dataset, DatasetDict


def _iter_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _clean_text(s: str) -> str:
    return " ".join(s.replace("\r", " ").replace("\n", "\n").split())


def _format_prompt(record: Dict[str, Any]) -> str:
    """Format instruction-style prompt.

    Supports two export shapes:
    - {"instruction": ..., "input": ..., "output": ...}
    - {"context": ..., "answer": ...} (RAG preset)
    Falls back to treating the line as already-formatted text if neither schema matches.
    """
    if "instruction" in record and "output" in record:
        instr = _clean_text(str(record.get("instruction", "")))
        ipt = _clean_text(str(record.get("input", "")))
        tgt = _clean_text(str(record.get("output", "")))
        if ipt:
            text = f"Instruction:\n{instr}\n\nInput:\n{ipt}\n\nResponse:\n{tgt}"
        else:
            text = f"Instruction:\n{instr}\n\nResponse:\n{tgt}"
        return text
    if "context" in record and "answer" in record:
        ctx = _clean_text(str(record.get("context", "")))
        ans = _clean_text(str(record.get("answer", "")))
        return f"Context:\n{ctx}\n\nResponse:\n{ans}"
    # Already formatted text
    if "text" in record:
        return _clean_text(str(record["text"]))
    # Fallback best-effort
    return _clean_text(json.dumps(record, ensure_ascii=False))


def build_sft_dataset(
    *, input_path: str, split_ratio: float = 0.1, max_seq_len: int = 2048
) -> DatasetDict:
    """Build a DatasetDict(train/validation) from a JSONL export.

    Each example has a single field "text" containing the fully formatted
    input-target pair for SFT-style training.
    """
    texts: list[str] = []
    for rec in _iter_jsonl(input_path):
        text = _format_prompt(rec)
        # simple truncation to contain memory use in smoke runs
        if len(text) > max_seq_len * 2:  # rough char proxy for tokens
            text = text[: max_seq_len * 2]
        texts.append(text)

    if not texts:
        raise ValueError("no records in input JSONL")

    split = max(1, int(len(texts) * split_ratio))
    val = texts[:split]
    train = texts[split:] or texts[:1]

    ds_train = Dataset.from_dict({"text": train})
    ds_val = Dataset.from_dict({"text": val})
    return DatasetDict(train=ds_train, validation=ds_val)

