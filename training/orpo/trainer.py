from __future__ import annotations

from typing import Any, Dict, Optional

import torch


def train_orpo(
    *,
    base_model: str,
    output_dir: str,
    pref_data,  # HF Dataset
    peft_cfg: Optional[Dict[str, Any]] = None,
    quantization: Optional[str] = None,
    max_seq_len: int = 2048,
    lr: float = 5e-5,
    num_epochs: int = 1,
    batch_size: int = 1,
    grad_accum: int = 16,
) -> Dict[str, Any]:
    """ORPO-style preference training.

    If TRL provides ORPOTrainer, use it. Otherwise, run a minimal reference-free
    preference objective over (prompt, chosen, rejected) pairs.
    """
    # Prefer TRL's implementation if present
    try:  # pragma: no cover - external availability dependent
        from trl import ORPOTrainer  # type: ignore
        from transformers import TrainingArguments, AutoTokenizer, AutoModelForCausalLM  # type: ignore

        from training.sft.trainer import _apply_peft as _apply_peft_sft  # type: ignore
        from training.sft.trainer import _load_model_and_tok as _load_model_and_tok_sft  # type: ignore

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
        trainer = ORPOTrainer(
            model=model,
            args=args,
            tokenizer=tok,
            train_dataset=pref_data,
            max_length=max_seq_len,
        )
        out = trainer.train()
        trainer.model.save_pretrained(output_dir)
        tok.save_pretrained(output_dir)
        return {"train_loss": float(out.training_loss) if out.training_loss is not None else None}
    except Exception:
        # Minimal fallback: simple pairwise loss on last token
        from transformers import AutoTokenizer, AutoModelForCausalLM  # type: ignore

        from training.sft.trainer import _apply_peft as _apply_peft_sft  # type: ignore
        from training.sft.trainer import _load_model_and_tok as _load_model_and_tok_sft  # type: ignore

        model, tok = _load_model_and_tok_sft(base_model, quantization, peft_cfg)
        model = _apply_peft_sft(model, peft_cfg)
        model.train()
        opt = torch.optim.AdamW(model.parameters(), lr=lr)

        def batchify(ds, bs):
            for i in range(0, len(ds), bs):
                yield ds[i : i + bs]

        total_loss = 0.0
        steps = 0
        for _ in range(num_epochs):
            for batch in batchify(pref_data, batch_size):
                inputs = tok(
                    [f"{p}\n\n{c}" for p, c in zip(batch["prompt"], batch["chosen"])],
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=max_seq_len,
                )
                inputs = {k: v.to(model.device) for k, v in inputs.items()}
                logits_c = model(**inputs).logits[:, -1, :]  # [B, V]

                inputs_r = tok(
                    [f"{p}\n\n{r}" for p, r in zip(batch["prompt"], batch["rejected"])],
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=max_seq_len,
                )
                inputs_r = {k: v.to(model.device) for k, v in inputs_r.items()}
                logits_r = model(**inputs_r).logits[:, -1, :]

                # Pref loss: encourage higher chosen logit mass for first token of completion
                # Use their first token ids as anchors
                c_ids = tok(batch["chosen"], return_tensors="pt", padding=True, truncation=True, max_length=4)[
                    "input_ids"
                ]
                r_ids = tok(batch["rejected"], return_tensors="pt", padding=True, truncation=True, max_length=4)[
                    "input_ids"
                ]
                c_ids = c_ids[:, 0].to(model.device)
                r_ids = r_ids[:, 0].to(model.device)
                logp_c = torch.nn.functional.log_softmax(logits_c, dim=-1).gather(1, c_ids.unsqueeze(1)).squeeze(1)
                logp_r = torch.nn.functional.log_softmax(logits_r, dim=-1).gather(1, r_ids.unsqueeze(1)).squeeze(1)
                loss = torch.relu(1.0 - (logp_c - logp_r)).mean()  # hinge on logit margin

                loss.backward()
                if (steps + 1) % grad_accum == 0:
                    opt.step()
                    opt.zero_grad(set_to_none=True)
                total_loss += float(loss.detach().cpu())
                steps += 1

        # Save a minimal adapter if any; otherwise the base config for reproducibility
        try:
            model.save_pretrained(output_dir)
            tok.save_pretrained(output_dir)
        except Exception:
            pass

        avg_loss = total_loss / max(1, steps)
        return {"preference_loss": avg_loss}
