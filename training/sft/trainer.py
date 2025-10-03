from __future__ import annotations

import math
import os
import shutil
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import torch
from datasets import DatasetDict


@dataclass
class TrainResult:
    metrics: Dict[str, Any]
    artifact_dir: str


def _load_model_and_tok(base_model: str, quantization: Optional[str], peft_cfg: Optional[Dict[str, Any]]):
    from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore

    quantization_config = None
    torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    device_map = "auto" if torch.cuda.is_available() else None

    if quantization == "int4":
        # Prefer config provided by QLoRA strategy
        if peft_cfg and peft_cfg.get("type") == "qlora" and peft_cfg.get("quantization_config") is not None:
            quantization_config = peft_cfg["quantization_config"]
        else:  # best-effort local BitsAndBytesConfig
            try:
                from transformers import BitsAndBytesConfig  # type: ignore

                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch_dtype
                )
            except Exception:
                quantization_config = None

    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=torch_dtype,
        device_map=device_map,
        quantization_config=quantization_config,
    )
    tok = AutoTokenizer.from_pretrained(base_model, use_fast=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    return model, tok


def _apply_peft(model, peft_cfg: Optional[Dict[str, Any]]):
    if not peft_cfg:
        return model

    cfg = peft_cfg.get("config")
    if cfg is None:
        raise ValueError("peft_cfg must include a 'config' entry when PEFT is enabled")

    from peft import get_peft_model  # type: ignore

    return get_peft_model(model, cfg)  # type: ignore[arg-type]


def _save_artifacts(trainer, tokenizer, output_dir: str) -> str:
    model_to_save = getattr(trainer, "model_wrapped", None) or trainer.model
    is_peft = hasattr(model_to_save, "peft_config")

    target_dir = os.path.join(output_dir, "adapter" if is_peft else "model")
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    os.makedirs(target_dir, exist_ok=True)

    model_to_save.save_pretrained(target_dir)
    tokenizer.save_pretrained(target_dir)
    return target_dir


def _sanitize_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for k, v in metrics.items():
        if isinstance(v, float) and math.isnan(v):
            cleaned[k] = None
        else:
            cleaned[k] = v
    return cleaned


def train_sft(
    *,
    base_model: str,
    output_dir: str,
    data: DatasetDict,
    peft_cfg: Optional[Dict[str, Any]] = None,
    quantization: Optional[str] = None,
    max_seq_len: int = 2048,
    lr: float = 2e-4,
    num_epochs: int = 1,
    batch_size: int = 1,
    grad_accum: int = 16,
    eval_dataset_key: str = "validation",
    checkpoint_steps: Optional[int] = None,
    save_total_limit: Optional[int] = None,
    resume_from_checkpoint: Optional[str] = None,
) -> TrainResult:
    """Run SFT using TRL's SFTTrainer.

    Expects the dataset to have a 'text' field containing the packed prompt+target string.
    Returns metrics together with the directory that holds the saved adapter/tokenizer artifacts.
    """
    from trl import SFTTrainer, SFTConfig  # type: ignore

    model, tok = _load_model_and_tok(base_model, quantization, peft_cfg)
    model = _apply_peft(model, peft_cfg)

    effective_max_len = max(128, min(max_seq_len, 2048 if torch.cuda.is_available() else 512))

    ckpt_steps = checkpoint_steps if checkpoint_steps and checkpoint_steps > 0 else None
    save_limit = save_total_limit if save_total_limit is not None else 2
    save_limit = max(1, save_limit)
    save_strategy = "steps" if ckpt_steps else "no"
    save_steps = max(1, ckpt_steps or 50)

    args = SFTConfig(
        output_dir=output_dir,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=max(1, batch_size),
        gradient_accumulation_steps=grad_accum if torch.cuda.is_available() else max(1, min(grad_accum, 2)),
        num_train_epochs=num_epochs,
        learning_rate=lr,
        eval_strategy="steps" if eval_dataset_key in data else "no",
        eval_steps=10,
        save_total_limit=1,
        logging_steps=5,
        report_to=[],
        fp16=False,
        bf16=False,
        dataset_text_field="text",
        max_length=effective_max_len,
        packing=False,
    )

    trainer = SFTTrainer(
        model=model,
        args=args,
        train_dataset=data["train"],
        eval_dataset=data.get(eval_dataset_key),
        processing_class=tok,
    )

    t0 = time.time()
    resume_path = (
        resume_from_checkpoint
        if resume_from_checkpoint and os.path.isdir(resume_from_checkpoint)
        else None
    )
    train_kwargs: dict[str, Any] = {}
    if resume_path:
        train_kwargs["resume_from_checkpoint"] = resume_path
    out = trainer.train(**train_kwargs)
    duration = time.time() - t0
    artifact_dir = _save_artifacts(trainer, tok, output_dir)

    train_loss = float(out.training_loss) if hasattr(out, "training_loss") and out.training_loss is not None else None
    eval_loss = None
    if trainer.state.log_history:
        for entry in reversed(trainer.state.log_history):
            if "eval_loss" in entry:
                eval_loss = float(entry["eval_loss"])  # type: ignore
                break

    metrics = _sanitize_metrics(
        {
            "train_loss": train_loss,
            "eval_loss": eval_loss,
            "duration_sec": duration,
        }
    )
    return TrainResult(metrics=metrics, artifact_dir=artifact_dir)
