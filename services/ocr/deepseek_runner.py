from __future__ import annotations

import base64
import io
import json
import logging
import os
import time
from typing import Any, Iterable, Literal, Optional

from PIL import Image

from services.ocr.base import OCRResult, OCRRunner, OCRUnavailableError

logger = logging.getLogger(__name__)


class DeepseekOCRRunner(OCRRunner):
    """GPU-only DeepSeek OCR runner supporting transformers + vLLM runtimes."""

    backend_name = "deepseek"

    def __init__(
        self,
        *,
        model: str,
        runtime: Literal["transformers", "vllm"] = "transformers",
        max_new_tokens: int = 1024,
    ) -> None:
        self.model = model
        self.runtime = runtime
        self.max_new_tokens = max_new_tokens
        self._processor = None
        self._model = None
        self._tokenizer = None
        self._llm = None
        self._sampling_params = None

    def run(
        self,
        image_bytes: bytes,
        *,
        mode: Literal["text", "markdown"] = "text",
        langs: Optional[Iterable[str]] = None,
        **opts: Any,
    ) -> OCRResult:
        if not self._has_gpu():
            raise OCRUnavailableError("DeepSeek OCR requires a CUDA-enabled GPU")
        prompt = self._prompt_for_mode(mode)
        started = time.perf_counter()
        if self.runtime == "vllm":
            text = self._run_vllm(image_bytes, prompt)
        else:
            text = self._run_transformers(image_bytes, prompt)
        latency = time.perf_counter() - started
        meta = {
            "backend": self.backend_name,
            "runtime": self.runtime,
            "model": self.model,
            "mode": mode,
            "latency_s": round(latency, 3),
            "prompt": prompt,
        }
        result_text = text.strip()
        return OCRResult(
            text=result_text if mode == "text" else "",
            md=result_text if mode == "markdown" else None,
            meta=meta,
            ctx_compressed=self._compress(result_text),
        )

    # Helpers -----------------------------------------------------------------
    def _has_gpu(self) -> bool:
        try:
            import torch

            return torch.cuda.is_available()
        except Exception:  # pragma: no cover
            return False

    def _prompt_for_mode(self, mode: str) -> str:
        if mode == "markdown":
            return "Convert the document to markdown."
        return "Free OCR."

    def _run_transformers(self, image_bytes: bytes, prompt: str) -> str:
        processor = self._ensure_processor()
        model = self._ensure_model()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        inputs = processor(
            images=image, text=prompt, return_tensors="pt"
        ).to(model.device)
        generate_ids = model.generate(
            **inputs,
            max_new_tokens=self.max_new_tokens,
            do_sample=False,
            pad_token_id=self._pad_token_id(),
        )
        output = processor.batch_decode(generate_ids, skip_special_tokens=True)[0]
        return output

    def _run_vllm(self, image_bytes: bytes, prompt: str) -> str:
        llm = self._ensure_vllm()
        sampling = self._ensure_sampling_params()
        payload = self._build_conversation(image_bytes, prompt)
        outputs = llm.generate([payload], sampling_params=sampling)
        if not outputs:
            return ""
        return outputs[0].outputs[0].text

    def _ensure_processor(self):
        if self._processor is None:
            try:
                from transformers import AutoProcessor
            except Exception as exc:  # pragma: no cover
                raise OCRUnavailableError(
                    "transformers is required for DeepSeek OCR"
                ) from exc
            self._processor = AutoProcessor.from_pretrained(
                self.model, trust_remote_code=True
            )
        return self._processor

    def _ensure_model(self):
        if self._model is None:
            try:
                from transformers import AutoModelForCausalLM
                import torch
            except Exception as exc:  # pragma: no cover
                raise OCRUnavailableError(
                    "transformers/torch stack missing"
                ) from exc
            kwargs: dict[str, Any] = {
                "torch_dtype": torch.bfloat16,
                "trust_remote_code": True,
                "device_map": "auto",
            }
            if self._flash_attention_available():
                kwargs["attn_implementation"] = "flash_attention_2"
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model, **kwargs
            )
        return self._model

    def _pad_token_id(self) -> int | None:
        if self._tokenizer is None:
            try:
                from transformers import AutoTokenizer
            except Exception as exc:  # pragma: no cover
                raise OCRUnavailableError("tokenizer missing") from exc
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model, trust_remote_code=True
            )
        return getattr(self._tokenizer, "eos_token_id", None)

    def _ensure_vllm(self):
        if self._llm is None:
            try:
                from vllm import LLM
            except Exception as exc:  # pragma: no cover
                raise OCRUnavailableError("vLLM runtime not installed") from exc
            tensor_parallel_size = int(os.getenv("DEEPSEEK_VLLM_TP_SIZE", "1"))
            self._llm = LLM(
                model=self.model,
                tensor_parallel_size=tensor_parallel_size,
            )
        return self._llm

    def _ensure_sampling_params(self):
        if self._sampling_params is None:
            try:
                from vllm import SamplingParams
            except Exception as exc:  # pragma: no cover
                raise OCRUnavailableError("vLLM runtime not installed") from exc
            self._sampling_params = SamplingParams(
                temperature=0.0,
                top_p=0.9,
                max_tokens=self.max_new_tokens,
            )
        return self._sampling_params

    def _build_conversation(self, image_bytes: bytes, prompt: str) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        convo = [
            {"role": "system", "content": "You are a meticulous OCR engine."},
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": encoded},
                    {"type": "text", "text": prompt},
                ],
            },
        ]
        return json.dumps(convo)

    def _flash_attention_available(self) -> bool:
        try:  # pragma: no cover
            import importlib.util

            return importlib.util.find_spec("flash_attn") is not None
        except Exception:
            return False


__all__ = ["DeepseekOCRRunner"]
