from __future__ import annotations

import os

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
    checkpoint_steps: Optional[int] = None,
    save_total_limit: Optional[int] = None,
    resume_from_checkpoint: Optional[str] = None,
    manual_checkpoint_name: str = "manual_checkpoint.pt",
) -> Dict[str, Any]:
    """ORPO-style preference training.

    If TRL provides ORPOTrainer, use it. Otherwise, run a minimal reference-free
    preference objective over (prompt, chosen, rejected) pairs.
    """
    ckpt_steps = checkpoint_steps if checkpoint_steps and checkpoint_steps > 0 else None
    save_limit = save_total_limit if save_total_limit is not None else 2
    save_limit = max(1, save_limit)
    save_strategy = "steps" if ckpt_steps else "no"
    save_steps = max(1, ckpt_steps or 50)

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
        train_kwargs: dict[str, Any] = {}
        resume_dir = resume_from_checkpoint if resume_from_checkpoint and os.path.isdir(resume_from_checkpoint) else None
        if resume_dir:
            train_kwargs["resume_from_checkpoint"] = resume_dir
        out = trainer.train(**train_kwargs)
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

        manual_ckpt_path = os.path.join(output_dir, manual_checkpoint_name)
        if resume_from_checkpoint and os.path.isfile(resume_from_checkpoint):
            manual_ckpt_path = resume_from_checkpoint
        manual_dir = os.path.dirname(manual_ckpt_path)
        if manual_dir:
            os.makedirs(manual_dir, exist_ok=True)

        start_epoch = 0
        start_step = 0
        processed_steps = 0
        start_global = 0
        if os.path.isfile(manual_ckpt_path):
            try:
                state = torch.load(manual_ckpt_path, map_location="cpu")
            except Exception:
                state = None
            if isinstance(state, dict):
                model_state = state.get("model")
                if isinstance(model_state, dict):
                    model.load_state_dict(model_state, strict=False)
                opt_state = state.get("optimizer")
                if isinstance(opt_state, dict):
                    opt.load_state_dict(opt_state)
                start_epoch = int(state.get("epoch", 0))
                start_step = int(state.get("step", 0))
                processed_steps = int(state.get("global_step", 0))
                start_global = processed_steps

        opt.zero_grad(set_to_none=True)

        def batchify(ds, bs):
            for i in range(0, len(ds), bs):
                yield ds[i : i + bs]

        total_loss = 0.0
        last_epoch = start_epoch
        last_step_idx = start_step - 1
        for epoch in range(start_epoch, num_epochs):
            last_epoch = epoch
            epoch_start_step = start_step if epoch == start_epoch else 0
            for step_idx, batch in enumerate(batchify(pref_data, batch_size)):
                if step_idx < epoch_start_step:
                    continue
                last_step_idx = step_idx
                inputs = tok(
                    [f"{p}\n\n{c}" for p, c in zip(batch['prompt'], batch['chosen'])],
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=max_seq_len,
                )
                inputs = {k: v.to(model.device) for k, v in inputs.items()}
                logits_c = model(**inputs).logits[:, -1, :]

                inputs_r = tok(
                    [f"{p}\n\n{r}" for p, r in zip(batch['prompt'], batch['rejected'])],
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=max_seq_len,
                )
                inputs_r = {k: v.to(model.device) for k, v in inputs_r.items()}
                logits_r = model(**inputs_r).logits[:, -1, :]

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
                loss = torch.relu(1.0 - (logp_c - logp_r)).mean()

                loss.backward()
                processed_steps += 1
                if processed_steps % grad_accum == 0:
                    opt.step()
                    opt.zero_grad(set_to_none=True)
                total_loss += float(loss.detach().cpu())

                if ckpt_steps and processed_steps % ckpt_steps == 0:
                    try:
                        torch.save(
                            {
                                "model": model.state_dict(),
                                "optimizer": opt.state_dict(),
                                "epoch": epoch,
                                "step": step_idx + 1,
                                "global_step": processed_steps,
                            },
                            manual_ckpt_path,
                        )
                    except Exception:
                        pass
            start_step = 0

        # Always persist the latest weights to support resumes
        try:
            torch.save(
                {
                    "model": model.state_dict(),
                    "optimizer": opt.state_dict(),
                    "epoch": last_epoch,
                    "step": last_step_idx + 1,
                    "global_step": processed_steps,
                },
                manual_ckpt_path,
            )
        except Exception:
            pass

        try:
            model.save_pretrained(output_dir)
            tok.save_pretrained(output_dir)
        except Exception:
            pass

        new_steps = max(1, processed_steps - start_global)
        avg_loss = total_loss / new_steps
        return {"preference_loss": avg_loss}
