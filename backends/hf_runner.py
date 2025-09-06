from __future__ import annotations

import os
from typing import Optional, List

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore

try:
    from peft import PeftModel  # type: ignore
except Exception:  # pragma: no cover
    PeftModel = None  # type: ignore


class HFRunner:
    """Transformers-based ModelRunner implementation.

    - load_base: loads a base causal LM, optionally with int4 quantization if available
    - load_adapter: loads a PEFT adapter from local path (unzipped directory)
    - generate: simple text generation with optional system prompt
    """

    def __init__(self) -> None:
        self.model = None
        self.tokenizer = None

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
        self.tokenizer = AutoTokenizer.from_pretrained(base_model, use_fast=True)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

    def load_adapter(self, adapter_path: Optional[str]) -> None:
        if adapter_path is None or not os.path.exists(adapter_path):
            return
        if PeftModel is None:
            return
        self.model = PeftModel.from_pretrained(self.model, adapter_path)  # type: ignore[arg-type]

    def _build_prompt(self, prompt: str, system_prompt: Optional[str]) -> str:
        if system_prompt:
            return f"<|system|>\n{system_prompt}\n\n<|user|>\n{prompt}\n\n<|assistant|>\n"
        return prompt

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
        inputs = self.tokenizer(ptxt, return_tensors="pt").to(self.model.device)
        with torch.no_grad():
            gen = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=temperature > 0,
                temperature=temperature,
                eos_token_id=self.tokenizer.eos_token_id,
                pad_token_id=self.tokenizer.pad_token_id,
            )
        out = self.tokenizer.decode(gen[0], skip_special_tokens=True)
        # crude stop handling
        if stop:
            for s in stop:
                if s in out:
                    out = out.split(s)[0]
                    break
        return out


__all__ = ["HFRunner"]

