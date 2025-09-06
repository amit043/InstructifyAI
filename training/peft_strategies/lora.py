from __future__ import annotations

from typing import Any, Dict, Optional


def lora_config(
    *, r: int = 16, alpha: int = 32, dropout: float = 0.1, target_modules: Optional[list[str]] = None
) -> Dict[str, Any]:
    """Standard LoRA PEFT configuration dict.

    Returns a dict with keys: {"type": "lora", "config": peft.LoraConfig}
    """
    from peft import LoraConfig  # type: ignore

    kwargs: Dict[str, Any] = dict(
        r=r,
        lora_alpha=alpha,
        lora_dropout=dropout,
        bias="none",
        task_type="CAUSAL_LM",
    )
    if target_modules:
        kwargs["target_modules"] = target_modules
    cfg = LoraConfig(**kwargs)
    cfg._name = "lora"  # type: ignore[attr-defined]
    return {"type": "lora", "config": cfg}

