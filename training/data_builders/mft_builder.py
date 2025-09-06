from __future__ import annotations

import json
from typing import Any, Dict, Iterable

from datasets import DatasetDict, Dataset

from .sft_builder import _iter_jsonl, _format_prompt, _clean_text


def build_mft_dataset(
    *, input_path: str, split_ratio: float = 0.1, teacher_outputs_path: str | None = None
) -> DatasetDict:
    """Mini-Finetuning dataset: wrap SFT data and add corrective fields.

    If ``teacher_outputs_path`` is provided, it must be JSONL with the same number
    of lines as ``input_path``. Each line should include a ``corrective`` field
    (string). If not provided, use a self-consistency placeholder (duplicate target).
    """
    base_records: list[Dict[str, Any]] = list(_iter_jsonl(input_path))
    texts: list[str] = []
    corrective: list[str] = []

    teacher_iter: Iterable[Dict[str, Any]] | None = (
        _iter_jsonl(teacher_outputs_path) if teacher_outputs_path else None
    )
    teacher_list = list(teacher_iter) if teacher_iter is not None else None

    for idx, rec in enumerate(base_records):
        text = _format_prompt(rec)
        texts.append(text)
        corr = None
        if teacher_list is not None and idx < len(teacher_list):
            t = teacher_list[idx]
            corr = t.get("corrective") or t.get("output") or t.get("answer")
        if corr is None:
            # self-consistency placeholder: use the target embedded in the text
            corr = text.split("Response:\n", 1)[-1] if "Response:\n" in text else text
        corrective.append(_clean_text(str(corr)))

    if not texts:
        raise ValueError("no records in input JSONL")

    split = max(1, int(len(texts) * split_ratio))
    val_idx = list(range(0, split))
    train_idx = list(range(split, len(texts))) or [0]

    def _subset(ix: list[int]) -> Dataset:
        return Dataset.from_dict({
            "text": [texts[i] for i in ix],
            "corrective": [corrective[i] for i in ix],
        })

    return DatasetDict(train=_subset(train_idx), validation=_subset(val_idx))

