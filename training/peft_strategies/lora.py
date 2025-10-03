from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Union

TargetModules = Union[str, Sequence[str]]


def lora_config(
    *, r: int = 16, alpha: int = 32, dropout: float = 0.1, target_modules: Optional[TargetModules] = None
) -> Dict[str, Any]:
    """Standard LoRA PEFT configuration dict.

    Returns a dict with keys: {"type": "lora", "config": peft.LoraConfig}
    """
    from peft import LoraConfig  # type: ignore

    normalized_targets: TargetModules
    if target_modules is None:
        normalized_targets = "all-linear"
    elif isinstance(target_modules, (list, tuple, set)):
        normalized_targets = list(target_modules)
    else:
        normalized_targets = target_modules

    kwargs: Dict[str, Any] = dict(
        r=r,
        lora_alpha=alpha,
        lora_dropout=dropout,
        bias="none",
        task_type="CAUSAL_LM",
    )
    kwargs["target_modules"] = normalized_targets
    cfg = LoraConfig(**kwargs)
    cfg._name = "lora"  # type: ignore[attr-defined]
    return {"type": "lora", "config": cfg}

