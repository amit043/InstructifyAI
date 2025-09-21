from __future__ import annotations

from typing import Any, Dict, Optional

import torch
from datasets import DatasetDict

from training.sft.trainer import (
    TrainResult,
    _apply_peft as _apply_peft_sft,
    _load_model_and_tok as _load_model_and_tok_sft,
    _save_artifacts as _save_artifacts_sft,
)


def train_mft(
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
    teacher_outputs_path: str | None = None,
) -> TrainResult:
    """Mini-Finetuning (corrective distillation) trainer.

    This reuses TRL's SFTTrainer but applies a small corrective term based on the
    'corrective' field included in the dataset.
    Returns metrics together with the adapter/tokenizer artifact directory.
    """
    from trl import SFTTrainer  # type: ignore
    from transformers import TrainingArguments, DataCollatorForLanguageModeling  # type: ignore

    model, tok = _load_model_and_tok_sft(base_model, quantization, peft_cfg)
    model = _apply_peft_sft(model, peft_cfg)

    args = TrainingArguments(
        output_dir=output_dir,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        num_train_epochs=num_epochs,
        learning_rate=lr,
        logging_steps=5,
        report_to=[],
        fp16=torch.cuda.is_available(),
    )
    collator = DataCollatorForLanguageModeling(tok, mlm=False)

    class _MFTTrainer(SFTTrainer):
        def compute_loss(self, model, inputs, return_outputs=False):  # type: ignore[override]
            # Base loss
            loss, outputs = super().compute_loss(model, inputs, return_outputs=True)
            # Simple corrective loss: encourage model to generate tokens from 'corrective'
            # We do this by computing a cross-entropy on corrective token ids against logits
            # at the final positions (cheap proxy). If corrective missing, skip.
            corrective_texts = inputs.get("corrective", None)
            corr_term = torch.tensor(0.0, device=loss.device)
            if corrective_texts is not None:
                # Tokenize corrective targets
                corr_tok = tok(list(corrective_texts), return_tensors="pt", padding=True, truncation=True, max_length=128)
                corr_tok = {k: v.to(loss.device) for k, v in corr_tok.items()}
                logits = outputs.logits  # [B, T, V]
                # Take last-step logits for each sample
                last_logits = logits[:, -1, :]  # [B, V]
                # Take first token of corrective as a cheap anchor
                corr_ids = corr_tok["input_ids"][:, 0]  # [B]
                ce = torch.nn.functional.cross_entropy(last_logits, corr_ids, reduction="mean")
                corr_term = ce
            total = loss + 0.05 * corr_term
            return (total, outputs) if return_outputs else total

    trainer = _MFTTrainer(
        model=model,
        tokenizer=tok,
        train_dataset=data["train"],
        eval_dataset=data.get("validation"),
        args=args,
        dataset_text_field="text",
        max_seq_length=max_seq_len,
        packing=True,
        data_collator=collator,
    )

    out = trainer.train()
    artifact_dir = _save_artifacts_sft(trainer, tok, output_dir)

    metrics = {"train_loss": float(out.training_loss) if out.training_loss is not None else None}
    # Record a smoke metric suggesting improvement potential
    metrics["corrective_term_weight"] = 0.05
    return TrainResult(metrics=metrics, artifact_dir=artifact_dir)
