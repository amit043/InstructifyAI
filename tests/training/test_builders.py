import io
import json
import os
import tempfile

from training.data_builders.sft_builder import build_sft_dataset
from training.data_builders.mft_builder import build_mft_dataset
from training.data_builders.orpo_builder import build_pref_dataset


def _write_jsonl(lines):
    fd, path = tempfile.mkstemp(prefix="ds_", suffix=".jsonl")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")
    return path


def test_sft_and_mft_builder_basic():
    data = [
        {"instruction": "Summarize", "input": "A", "output": "AA"},
        {"instruction": "Summarize", "input": "B", "output": "BB"},
        {"instruction": "Summarize", "input": "C", "output": "CC"},
    ]
    path = _write_jsonl(data)
    ds = build_sft_dataset(input_path=path, split_ratio=0.33, max_seq_len=128)
    assert set(ds.keys()) == {"train", "validation"}
    assert "text" in ds["train"].column_names
    assert len(ds["train"]) >= 1 and len(ds["validation"]) >= 1

    mft = build_mft_dataset(input_path=path, split_ratio=0.33)
    assert set(mft.keys()) == {"train", "validation"}
    assert set(["text", "corrective"]).issubset(set(mft["train"].column_names))


def test_orpo_pref_builder_basic():
    data = [
        {"prompt": "Say hi", "chosen": "Hello", "rejected": "No"},
        {"instruction": "Greet", "input": None, "accepted": "Hi", "alternative": "..."},
    ]
    path = _write_jsonl(data)
    ds = build_pref_dataset(input_path=path)
    assert set(ds.column_names) == {"prompt", "chosen", "rejected"}
    assert len(ds) == 2

