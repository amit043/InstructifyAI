from __future__ import annotations

import os
from typing import List, Optional


class LlamaCppRunner:
    """llama.cpp-based ModelRunner implementation (CPU or partial GPU layers).

    This runner uses the `llama-cpp-python` package to load GGUF models and
    generate text. It aims to satisfy the `ModelRunner` protocol in
    `training/interfaces/backends.py`.

    Notes
    - Expects a local GGUF model file path in `load_base`.
    - Context length (`n_ctx`) can be set via env `LLAMA_CTX` or defaults to 4096.
    - Partial GPU offload can be configured via env `LLAMA_N_GPU_LAYERS`.
    - If `llama-cpp-python` is not installed, a clear ImportError is raised.
    """

    def __init__(self) -> None:
        self._llm = None

    def load_base(self, base_model: str, quantization: Optional[str] = "int4") -> None:
        """Load a GGUF model via llama.cpp.

        Parameters
        - base_model: path to a local `.gguf` file.
        - quantization: ignored; present for protocol compatibility. Use GGUF file.
        """
        try:
            from llama_cpp import Llama  # type: ignore
        except Exception as e:  # pragma: no cover - depends on env
            raise ImportError(
                "llama-cpp-python is required for LlamaCppRunner.\n"
                "Install with: pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121\n"
                "(Choose the appropriate wheel for your platform/GPU.)"
            ) from e

        # Use env to control context and GPU layer offload
        n_ctx = int(os.environ.get("LLAMA_CTX", "4096"))
        n_gpu_layers = int(os.environ.get("LLAMA_N_GPU_LAYERS", "0"))

        # Construct Llama instance
        self._llm = Llama(
            model_path=base_model,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            verbose=False,
        )

    def load_adapter(self, adapter_path: Optional[str]) -> None:
        """No-op for GGUF baseline; included for protocol compatibility."""
        return None

    def _build_prompt(self, prompt: str, system_prompt: Optional[str]) -> str:
        if system_prompt:
            return f"System: {system_prompt}\nUser: {prompt}\nAssistant:"
        return prompt

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
        stop: Optional[List[str]] = None,
    ) -> str:
        assert self._llm is not None, "model not loaded"

        # Try chat completion if system prompt provided; fallback to completion.
        if system_prompt:
            try:
                res = self._llm.create_chat_completion(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_new_tokens,
                    stop=stop,
                )
                text = res["choices"][0]["message"]["content"]
                return text or ""
            except Exception:
                # Fall through to plain completion
                pass

        ptxt = self._build_prompt(prompt, system_prompt)
        res = self._llm.create_completion(
            prompt=ptxt,
            temperature=temperature,
            max_tokens=max_new_tokens,
            stop=stop,
        )
        text = res["choices"][0].get("text") if res.get("choices") else ""
        return text or ""


__all__ = ["LlamaCppRunner"]

