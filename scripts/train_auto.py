from __future__ import annotations

import argparse
import os
import sys
import subprocess
from typing import Any, Dict, Optional

from core.hw import detect_hardware
from models.catalog import recommend_for_hw, CATALOG


def _find_hf_small_fallback() -> str:
    for e in CATALOG:
        if e.get("id") == "phi-3-mini-4k-instruct":
            return e.get("hf_id") or "microsoft/Phi-3-mini-4k-instruct"
    return "microsoft/Phi-3-mini-4k-instruct"


def _build_cmd(
    *,
    mode: str,
    project_id: str,
    base_model: str,
    quant: str,
    peft: str,
    data_path: str,
    epochs: int,
    batch_size: int,
    grad_accum: int,
    max_seq_len: int,
    lr: Optional[float],
) -> list[str]:
    cmd = [
        sys.executable,
        os.path.join("scripts", "train_adapter.py"),
        "--mode",
        mode,
        "--project-id",
        project_id,
        "--base-model",
        base_model,
        "--quantization",
        quant,
        "--peft",
        peft,
        "--data",
        data_path,
        "--epochs",
        str(epochs),
        "--batch-size",
        str(batch_size),
        "--grad-accum",
        str(grad_accum),
        "--max-seq-len",
        str(max_seq_len),
    ]
    if lr is not None:
        cmd += ["--lr", str(lr)]
    return cmd


def main() -> None:
    p = argparse.ArgumentParser("train_auto", description="Auto-select PEFT and training knobs based on hardware")
    p.add_argument("--project-id", required=True)
    p.add_argument("--data", required=True, help="Path to JSONL export or preference dataset")
    p.add_argument("--mode", choices=["sft", "mft", "orpo"], required=True)
    p.add_argument("--base-model", default=None, help="Override base HF model id")
    p.add_argument("--prefer-small", action="store_true", help="Bias towards smaller models when recommending")
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--lr", type=float, default=None)
    args = p.parse_args()

    hw = detect_hardware()
    print("[train_auto] Detected hardware:", hw)

    # Decide base model
    base_model = args.base_model
    preference = "small" if args.prefer_small else "balanced"
    rec = recommend_for_hw(hw, preference=preference)
    rec_ctx = int(rec.get("ctx", 4096))
    if not base_model:
        if rec.get("backend") == "hf" and rec.get("base_model"):
            base_model = rec["base_model"]
        else:
            # CPU or unknown → pick small HF fallback
            base_model = _find_hf_small_fallback()
            print(
                "[train_auto] No GPU/insufficient VRAM; using small HF base for training:",
                base_model,
            )

    # Heuristics for training knobs
    has_cuda = bool(hw.get("has_cuda", False))
    vram_mb = hw.get("vram_mb")
    vram_mb = int(vram_mb) if isinstance(vram_mb, (int, float)) else None

    peft = "lora"
    quant = "fp32"
    batch_size = 1
    grad_accum = 8
    max_seq_len = min(1024, rec_ctx)

    if has_cuda and (vram_mb or 0) >= 16000:
        peft = "dora"
        quant = "fp16"
        batch_size = 2
        grad_accum = 8
        max_seq_len = min(4096, rec_ctx)
        print(
            f"[train_auto] High VRAM ({vram_mb} MiB): selecting DoRA, fp16, bs={batch_size}, ga={grad_accum}, seq={max_seq_len}"
        )
    elif has_cuda and (vram_mb or 0) >= 8000:
        peft = "qlora"
        quant = "int4"
        batch_size = 1
        grad_accum = 16
        max_seq_len = min(2048, rec_ctx)
        print(
            f"[train_auto] Mid VRAM ({vram_mb} MiB): selecting QLoRA, int4, bs={batch_size}, ga={grad_accum}, seq={max_seq_len}"
        )
    else:
        # CPU or very low VRAM
        peft = "lora"
        quant = "fp32"
        batch_size = 1
        grad_accum = 8
        max_seq_len = min(1024, rec_ctx)
        print(
            "[train_auto] CPU/low-VRAM path: QLoRA is not ideal on CPU. "
            "Consider a smaller base or a llama.cpp pre-adapted model for inference."
        )

    cmd = _build_cmd(
        mode=args.mode,
        project_id=args.project_id,
        base_model=base_model,
        quant=quant,
        peft=peft,
        data_path=args.data,
        epochs=args.epochs,
        batch_size=batch_size,
        grad_accum=grad_accum,
        max_seq_len=max_seq_len,
        lr=args.lr,
    )

    print("[train_auto] Launching:", " ".join(cmd))
    try:
        # Stream output directly to console
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print("[train_auto] Training failed with exit code:", e.returncode)
        sys.exit(e.returncode)

    # Summary
    summary: Dict[str, Any] = {
        "project_id": args.project_id,
        "mode": args.mode,
        "base_model": base_model,
        "peft": peft,
        "quant": quant,
        "batch_size": batch_size,
        "grad_accum": grad_accum,
        "max_seq_len": max_seq_len,
        "epochs": args.epochs,
        "lr": args.lr,
    }
    print("[train_auto] Summary:", summary)


if __name__ == "__main__":
    main()

