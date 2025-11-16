from __future__ import annotations

import os
import logging
from typing import Optional, List, Iterable

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, LogitsProcessor, LogitsProcessorList  # type: ignore

try:
    from peft import PeftModel  # type: ignore
except Exception:  # pragma: no cover
    PeftModel = None  # type: ignore


class _SanitizeLogitsProcessor(LogitsProcessor):
    def __call__(self, input_ids, scores):  # type: ignore[override]
        if torch.isnan(scores).any() or torch.isinf(scores).any():
            scores = torch.nan_to_num(scores, nan=-1e4, posinf=1e4, neginf=-1e4)
        return scores


class HFRunner:
    """Transformers-based ModelRunner implementation.

    - load_base: loads a base causal LM, optionally with int4 quantization if available
    - load_adapter: loads a PEFT adapter from local path (unzipped directory)
    - generate: simple text generation with optional system prompt
    """

    def __init__(self) -> None:
        self.model = None
        self.tokenizer = None
        self._base_model_id: Optional[str] = None
        self._active_adapter_path: Optional[str] = None

    def load_base(self, base_model: str, quantization: Optional[str] = "int4") -> None:
        device_map = "auto" if torch.cuda.is_available() else None
        torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32

        quantization_config = None
        if quantization == "int4":
            try:
                from transformers import BitsAndBytesConfig  # type: ignore

                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch_dtype
                )
            except Exception:
                quantization_config = None

        self.model = AutoModelForCausalLM.from_pretrained(
            base_model,
            device_map=device_map,
            torch_dtype=torch_dtype,
            quantization_config=quantization_config,
        )
        self._base_model_id = base_model
        self.tokenizer = AutoTokenizer.from_pretrained(base_model, use_fast=True)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

    def load_adapter(self, adapter_path: Optional[str]) -> None:
        if adapter_path is None or not os.path.exists(adapter_path):
            return
        if PeftModel is None:
            return
        self.model = PeftModel.from_pretrained(self.model, adapter_path)  # type: ignore[arg-type]
        self._active_adapter_path = adapter_path

    def _build_prompt(self, prompt: str, system_prompt: Optional[str]) -> str:
        if system_prompt:
            return f"<|system|>\n{system_prompt}\n\n<|user|>\n{prompt}\n\n<|assistant|>\n"
        return prompt

    def _detect_model_device(self) -> torch.device:
        if self.model is None:
            return torch.device("cpu")
        try:
            return next(self.model.parameters()).device
        except Exception:
            return torch.device("cpu")

    def _prepare_inputs(self, prompt_text: str, device: torch.device) -> dict[str, torch.Tensor]:
        encoded = self.tokenizer(prompt_text, return_tensors="pt")
        return {k: v.to(device) if hasattr(v, "to") else v for k, v in encoded.items()}

    def _build_logits_processor(self, existing: Optional[object]) -> LogitsProcessorList:
        processors = LogitsProcessorList()
        if existing:
            if isinstance(existing, LogitsProcessorList):
                processors.extend(existing)
            elif isinstance(existing, LogitsProcessor):
                processors.append(existing)
            elif isinstance(existing, Iterable):
                for proc in existing:
                    if isinstance(proc, LogitsProcessor):
                        processors.append(proc)
        processors.append(_SanitizeLogitsProcessor())
        return processors

    def _decode_new_tokens(
        self,
        sequences,
        prompt_token_len: int,
        stop: Optional[List[str]],
    ) -> str:
        """Strip the prompt tokens before decoding to avoid echoing the context."""
        if sequences is None:
            return ""
        seq = sequences
        if hasattr(sequences, "ndim") and getattr(sequences, "ndim") >= 2:
            seq = sequences[0]
        elif isinstance(sequences, (list, tuple)) and sequences:
            seq = sequences[0]
        if hasattr(seq, "shape"):
            total = seq.shape[-1]
            if prompt_token_len > 0 and total >= prompt_token_len:
                seq = seq[prompt_token_len:]
            elif prompt_token_len > 0:
                seq = seq[:0]
        elif isinstance(seq, (list, tuple)):
            seq = seq[prompt_token_len:]
        if hasattr(seq, "detach"):
            seq = seq.detach()
        if hasattr(seq, "cpu"):
            seq = seq.cpu()
        tokens = seq.tolist() if hasattr(seq, "tolist") else list(seq)
        if not tokens:
            return ""
        text = self.tokenizer.decode(tokens, skip_special_tokens=True)
        if stop:
            for s in stop:
                if s and s in text:
                    text = text.split(s)[0]
                    break
        return text

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
        stop: Optional[List[str]] = None,
    ) -> str:
        assert self.model is not None and self.tokenizer is not None, "model not loaded"
        ptxt = self._build_prompt(prompt, system_prompt)
        model_device = self._detect_model_device()
        inputs = self._prepare_inputs(ptxt, model_device)
        prompt_token_len = 0
        input_ids = inputs.get("input_ids")
        if hasattr(input_ids, "shape"):
            prompt_token_len = int(input_ids.shape[-1])
        sample = temperature is not None and temperature > 0
        kwargs = dict(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=sample,
            eos_token_id=self.tokenizer.eos_token_id,
            pad_token_id=self.tokenizer.pad_token_id,
        )
        if sample:
            kwargs["temperature"] = temperature
        existing_processors = kwargs.pop("logits_processor", None)
        kwargs["logits_processor"] = self._build_logits_processor(existing_processors)
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        try:
            with torch.no_grad():
                gen = self.model.generate(**kwargs)
        except Exception as exc:
            msg = str(exc).lower()
            if sample and (
                "probability tensor contains" in msg or "device-side assert triggered" in msg
            ):
                logger = logging.getLogger(__name__)
                logger.warning(
                    "hf_runner fallback to greedy decode due to invalid sampling probabilities (%s)",
                    msg.splitlines()[0] if msg else exc.__class__.__name__,
                )

                if torch.cuda.is_available():
                    try:
                        torch.cuda.synchronize()
                    except Exception:
                        pass
                    try:
                        torch.cuda.empty_cache()
                    except Exception:
                        pass

                fallback_inputs = self._prepare_inputs(ptxt, model_device)
                fallback_prompt_len = 0
                fallback_input_ids = fallback_inputs.get("input_ids")
                if hasattr(fallback_input_ids, "shape"):
                    fallback_prompt_len = int(fallback_input_ids.shape[-1])
                fallback_kwargs = {
                    "input_ids": fallback_inputs.get("input_ids"),
                    "attention_mask": fallback_inputs.get("attention_mask"),
                    "max_new_tokens": max_new_tokens,
                    "do_sample": False,
                    "eos_token_id": self.tokenizer.eos_token_id,
                    "pad_token_id": self.tokenizer.pad_token_id,
                    "logits_processor": self._build_logits_processor(None),
                }
                fallback_kwargs = {k: v for k, v in fallback_kwargs.items() if v is not None}

                try:
                    with torch.no_grad():
                        gen = self.model.generate(**fallback_kwargs)
                    return self._decode_new_tokens(gen, fallback_prompt_len, stop)
                except Exception as second_exc:
                    logger.error("hf_runner greedy fallback failed: %s", second_exc)
                    raise
            raise
        return self._decode_new_tokens(gen, prompt_token_len, stop)


__all__ = ["HFRunner"]


