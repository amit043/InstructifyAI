from __future__ import annotations

from typing import Any, Dict, Optional


def dora_or_lora_config(
    *,
    r: int = 16,
    alpha: int = 32,
    dropout: float = 0.1,
    target_modules: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """Return a DoRA config if available in PEFT; fallback to LoRA with a warning.

    Uses peft.LoraConfig with ``use_dora=True`` when available. If PEFT does not
    support DoRA in the installed version, returns a standard LoRA config.
    """
    try:
        from peft import LoraConfig  # type: ignore
    except Exception:  # pragma: no cover - peft not installed
        raise RuntimeError("peft is required for DoRA/LoRA configuration")

    kwargs: Dict[str, Any] = dict(
        r=r,
        lora_alpha=alpha,
        lora_dropout=dropout,
        bias="none",
        task_type="CAUSAL_LM",
    )
    if target_modules:
        kwargs["target_modules"] = target_modules

    # Try DoRA flag on recent PEFT
    try:
        cfg = LoraConfig(**kwargs, use_dora=True)  # type: ignore[arg-type]
        cfg._name = "dora"  # type: ignore[attr-defined]
        return {"type": "dora", "config": cfg}
    except TypeError:
        # Fallback to plain LoRA
        cfg = LoraConfig(**kwargs)
        cfg._name = "lora"  # type: ignore[attr-defined]
        return {"type": "lora", "config": cfg, "warning": "DoRA not supported; using LoRA."}

