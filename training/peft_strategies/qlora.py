from __future__ import annotations

from typing import Any, Dict, Optional


def qlora_config(
    *, r: int = 16, alpha: int = 32, dropout: float = 0.1, target_modules: Optional[list[str]] = None
) -> Dict[str, Any]:
    """QLoRA PEFT configuration with bitsandbytes 4-bit quantization.

    Returns a dict with keys:
    - type: "qlora"
    - config: peft.LoraConfig (QLoRA still uses LoRA adapters)
    - quantization_config: transformers.BitsAndBytesConfig for nf4 int4
    """
    from peft import LoraConfig  # type: ignore
    try:
        from transformers import BitsAndBytesConfig  # type: ignore
    except Exception as e:  # pragma: no cover - transformers/bnb missing
        raise RuntimeError("transformers with bitsandbytes integration is required for QLoRA") from e

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
    cfg._name = "qlora"  # type: ignore[attr-defined]

    bnb_cfg = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype="float16",
        bnb_4bit_use_double_quant=True,
    )
    return {"type": "qlora", "config": cfg, "quantization_config": bnb_cfg}

