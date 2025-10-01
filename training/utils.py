from __future__ import annotations

import importlib
from typing import Any, Dict

from core.hw import detect_hardware


def ensure_training_environment_ready() -> None:
    required = ("peft",)
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        formatted = ", ".join(sorted(missing))
        raise RuntimeError(f"trainer dependencies missing: {formatted}. Rebuild trainer container with INSTALL_ML=1.")


def select_training_knobs(
    base_model: str | None,
    prefer_small: bool,
    ctx_hint: int = 4096,
) -> Dict[str, Any]:
    """Return PEFT/quant knobs based on host hardware characteristics."""
    hw = detect_hardware()
    has_cuda = bool(hw.get("has_cuda", False))
    vram_mb = hw.get("vram_mb")
    vram_mb = int(vram_mb) if isinstance(vram_mb, (int, float)) else None

    peft = "lora"
    quant = "fp32"
    batch_size = 1
    grad_accum = 2
    max_seq_len = min(1024, ctx_hint)

    if has_cuda and (vram_mb or 0) >= 16000:
        peft = "dora"
        quant = "fp16"
        batch_size = 2
        grad_accum = 8
        max_seq_len = min(4096, ctx_hint)
    elif has_cuda and (vram_mb or 0) >= 8000:
        peft = "qlora"
        quant = "int4"
        batch_size = 1
        grad_accum = 16
        max_seq_len = min(2048, ctx_hint)

    return {
        "peft": peft,
        "quant": quant,
        "batch_size": batch_size,
        "grad_accum": grad_accum,
        "max_seq_len": max_seq_len,
    }
