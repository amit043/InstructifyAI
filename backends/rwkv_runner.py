from __future__ import annotations

from typing import Optional, List


class RWKVRunner:
    """Experimental RWKV ModelRunner.

    Minimal implementation using the `rwkv` Python package. Adapters are treated
    as optional lightweight state/linear head overlays saved on disk. This module
    is marked experimental and intended for local demos only.
    """

    def __init__(self) -> None:
        self.model = None
        self.tokenizer = None
        self.adapter_state = None

    def load_base(self, base_model: str, quantization: Optional[str] = None) -> None:  # noqa: ARG002
        try:  # pragma: no cover - optional dep
            from rwkv.model import RWKV
            from rwkv.utils import PIPELINE
        except Exception as e:
            raise RuntimeError("rwkv package is required for RWKV backend") from e

        # RWKV uses its own tokenizer/pipeline
        self.model = RWKV(model=base_model, strategy="cpu fp32")
        self.tokenizer = PIPELINE("rwkv_vocab_v20230424")

    def load_adapter(self, adapter_path: Optional[str]) -> None:
        # Stub: load small python dict with delta state if present
        if adapter_path is None:
            return
        try:
            import json, os

            p = os.path.join(adapter_path, "rwkv_adapter.json")
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    self.adapter_state = json.load(f)
        except Exception:
            self.adapter_state = None

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
        stop: Optional[List[str]] = None,
    ) -> str:
        assert self.model is not None and self.tokenizer is not None
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        out = ""
        state = None
        for _ in range(max_new_tokens):
            token = self.tokenizer.encode(out or full_prompt)
            logits, state = self.model.forward(token, state)
            # Greedy / temperature sample
            import torch

            probs = torch.softmax(torch.tensor(logits) / max(1e-6, temperature), dim=-1)
            idx = int(torch.argmax(probs))
            out += self.tokenizer.decode([idx])
            if stop and any(s in out for s in stop):
                break
        return out


__all__ = ["RWKVRunner"]

