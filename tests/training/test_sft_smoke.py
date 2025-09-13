import os
import tempfile

import pytest


_HAS_DEPS = True
try:  # pragma: no cover - availability dependent
    import transformers  # noqa: F401
    import trl  # noqa: F401
    import peft  # noqa: F401
except Exception:  # pragma: no cover - availability dependent
    _HAS_DEPS = False


@pytest.mark.skipif(not _HAS_DEPS, reason="transformers/trl/peft required")
def test_sft_trains_tiny_model():
    from training.data_builders.sft_builder import build_sft_dataset
    from training.peft_strategies.lora import lora_config
    from training.sft.trainer import train_sft

    # tiny dataset
    import json

    lines = [
        {"instruction": "Echo", "input": "A", "output": "A"},
        {"instruction": "Echo", "input": "B", "output": "B"},
    ]
    fd, path = tempfile.mkstemp(prefix="sft_", suffix=".jsonl")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")

    ds = build_sft_dataset(input_path=path, split_ratio=0.5, max_seq_len=64)
    outdir = tempfile.mkdtemp(prefix="sft_out_")
    peft = lora_config()
    metrics = train_sft(
        base_model="sshleifer/tiny-gpt2",
        output_dir=outdir,
        data=ds,
        peft_cfg=peft,
        quantization=None,
        max_seq_len=64,
        lr=5e-5,
        num_epochs=1,
        batch_size=1,
        grad_accum=1,
    )
    assert os.path.exists(os.path.join(outdir, "config.json"))
    assert "train_loss" in metrics
