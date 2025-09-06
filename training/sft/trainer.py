from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import torch
from datasets import DatasetDict


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
    try:
        from peft import get_peft_model  # type: ignore

        return get_peft_model(model, peft_cfg["config"])  # type: ignore[index]
    except Exception:
        return model


def _save_artifacts(trainer, tokenizer, output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    trainer.model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)


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
) -> Dict[str, Any]:
    """Run SFT using TRL's SFTTrainer.

    Expects the dataset to have a 'text' field containing the packed prompt+target string.
    """
    from trl import SFTTrainer  # type: ignore
    from transformers import TrainingArguments, DataCollatorForLanguageModeling  # type: ignore

    model, tok = _load_model_and_tok(base_model, quantization, peft_cfg)
    model = _apply_peft(model, peft_cfg)

    args = TrainingArguments(
        output_dir=output_dir,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=max(1, batch_size),
        gradient_accumulation_steps=grad_accum,
        num_train_epochs=num_epochs,
        learning_rate=lr,
        evaluation_strategy="steps" if eval_dataset_key in data else "no",
        eval_steps=10,
        save_total_limit=1,
        logging_steps=5,
        report_to=[],
        fp16=torch.cuda.is_available(),
    )

    collator = DataCollatorForLanguageModeling(tok, mlm=False)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tok,
        train_dataset=data["train"],
        eval_dataset=data.get(eval_dataset_key),
        args=args,
        dataset_text_field="text",
        max_seq_length=max_seq_len,
        packing=True,
        data_collator=collator,
    )

    t0 = time.time()
    out = trainer.train()
    duration = time.time() - t0
    _save_artifacts(trainer, tok, output_dir)

    train_loss = float(out.training_loss) if hasattr(out, "training_loss") and out.training_loss is not None else None
    eval_loss = None
    if trainer.state.log_history:
        for e in reversed(trainer.state.log_history):
            if "eval_loss" in e:
                eval_loss = float(e["eval_loss"])  # type: ignore
                break

    return {
        "train_loss": train_loss,
        "eval_loss": eval_loss,
        "duration_sec": duration,
    }

