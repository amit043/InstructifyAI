from __future__ import annotations

import os
import tempfile
import threading
import zipfile
from functools import lru_cache
from typing import Any, Dict, Iterator, Optional

import sqlalchemy as sa
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker

from core.settings import get_settings
from core.hw import detect_hardware
from models.catalog import recommend_for_hw, cap_tokens_for_hw
from registry.adapters import get_active_adapter, list_adapters, activate_adapter, Adapter
from registry.storage import get_artifact


class AskPayload(BaseModel):
    project_id: str
    prompt: str
    max_new_tokens: int | None = None
    temperature: float | None = None
    adapter_id: str | None = None


app = FastAPI()


@lru_cache()
def _get_db_sessionmaker():
    settings = get_settings()
    engine = sa.create_engine(settings.database_url)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _download_and_unzip(s3_uri: str) -> str:
    tmp = get_artifact(s3_uri)
    # If zip, extract to temp dir
    if zipfile.is_zipfile(tmp):
        d = tempfile.mkdtemp(prefix="adapter_")
        with zipfile.ZipFile(tmp) as z:
            z.extractall(d)
        return d
    return os.path.dirname(tmp)


class ModelService:
    """Holds backend state and implements generation + streaming.

    - Detects hardware lazily.
    - If BASE_MODEL not set, recommends model/backend/quant from hardware.
    - Supports backends: "hf" (Transformers) and "llama_cpp" (GGUF via llama.cpp).
    - Applies adapters only for HF; llama.cpp ignores adapters.
    """

    def __init__(self) -> None:
        self.hw: Optional[Dict[str, Any]] = None
        self.choice: Optional[Dict[str, Any]] = None
        self.backend_name: Optional[str] = None
        self.quant: Optional[str] = None
        self.ctx: int = 4096
        self.max_new_tokens_cap: int = 1024
        self.backend: Any = None
        self.current_base_model: Optional[str] = None
        self.current_adapter_dir: Optional[str] = None

    def _resolve_choice(self) -> None:
        # Lazy hardware detection
        if self.hw is None:
            self.hw = detect_hardware()

        # Env overrides
        base_model_env = os.environ.get("BASE_MODEL")
        backend_env = os.environ.get("BASE_BACKEND", "hf").lower()
        quant_env = os.environ.get("QUANT")

        if base_model_env:
            # Use env-specified model
            self.backend_name = backend_env if backend_env in {"hf", "llama_cpp"} else "hf"
            self.quant = quant_env or ("gguf" if self.backend_name == "llama_cpp" else "int4")
            # Context: prefer LLAMA_CTX for llama.cpp; else default
            if self.backend_name == "llama_cpp":
                self.ctx = int(os.environ.get("LLAMA_CTX", "4096"))
            else:
                self.ctx = int(os.environ.get("CTX", "4096"))
            self.choice = {
                "backend": self.backend_name,
                "base_model": base_model_env,
                "quant": self.quant,
                "ctx": self.ctx,
            }
        else:
            # Recommend based on hardware
            rec = recommend_for_hw(self.hw or {})
            self.choice = rec
            self.backend_name = rec.get("backend", "hf")
            self.quant = rec.get("quant", "int4")
            self.ctx = int(rec.get("ctx", 4096))

        # Compute conservative cap
        self.max_new_tokens_cap = cap_tokens_for_hw(self.hw or {}, self.ctx)

        # Instantiate backend if needed
        if self.backend is None or self.backend_name not in {"hf", "llama_cpp"}:
            self.backend = None  # reset if invalid

        if self.backend is None:
            if self.backend_name == "llama_cpp":
                from backends.llama_cpp_runner import LlamaCppRunner

                self.backend = LlamaCppRunner()
            else:
                from backends.hf_runner import HFRunner

                self.backend = HFRunner()

    def ensure_loaded(self, base_model_override: Optional[str] = None, adapter_dir: Optional[str] = None) -> None:
        self._resolve_choice()

        # Decide base model to load
        base_model = base_model_override or (self.choice.get("base_model") if self.choice else None)
        if not base_model:
            raise HTTPException(status_code=500, detail="no base model resolved")

        # If backend/model changed, load base
        if self.current_base_model != base_model:
            self.backend.load_base(base_model, quantization=self.quant)
            self.current_base_model = base_model
            # reset adapter marker
            self.current_adapter_dir = None

        # Adapter applies to HF only
        if self.backend_name == "hf" and adapter_dir is not None and self.current_adapter_dir != adapter_dir:
            self.backend.load_adapter(adapter_dir)
            self.current_adapter_dir = adapter_dir

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
        stop: Optional[list[str]] = None,
    ) -> str:
        self._resolve_choice()
        capped = min(int(max_new_tokens), int(self.max_new_tokens_cap))
        return self.backend.generate(
            prompt,
            max_new_tokens=capped,
            temperature=temperature,
            system_prompt=system_prompt,
            stop=stop,
        )

    def stream(
        self,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
        stop: Optional[list[str]] = None,
    ) -> Iterator[str]:
        """Yield Server-Sent Events lines for generated tokens/text."""
        self._resolve_choice()
        capped = min(int(max_new_tokens), int(self.max_new_tokens_cap))

        # HF streaming via TextIteratorStreamer
        if self.backend_name == "hf":
            try:
                import torch  # type: ignore
                from transformers import TextIteratorStreamer  # type: ignore
            except Exception:  # pragma: no cover
                # Fallback to buffered generate
                text = self.backend.generate(
                    prompt,
                    max_new_tokens=capped,
                    temperature=temperature,
                    system_prompt=system_prompt,
                    stop=stop,
                )
                yield f"data: {text}\n\n"
                yield "data: [DONE]\n\n"
                return

            model = getattr(self.backend, "model", None)
            tokenizer = getattr(self.backend, "tokenizer", None)
            if model is None or tokenizer is None:
                raise HTTPException(status_code=500, detail="HF backend not loaded")

            if system_prompt:
                ptxt = f"<|system|>\n{system_prompt}\n\n<|user|>\n{prompt}\n\n<|assistant|>\n"
            else:
                ptxt = prompt

            streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
            inputs = tokenizer(ptxt, return_tensors="pt").to(model.device)

            gen_kwargs = dict(
                **inputs,
                max_new_tokens=capped,
                do_sample=temperature > 0,
                temperature=temperature,
                eos_token_id=tokenizer.eos_token_id,
                pad_token_id=tokenizer.pad_token_id,
                streamer=streamer,
            )

            # Run generation in a background thread
            thread = threading.Thread(target=model.generate, kwargs=gen_kwargs)
            thread.start()

            buffer = ""
            try:
                for new_text in streamer:
                    buffer += new_text
                    # crude stop handling
                    stop_hit = False
                    if stop:
                        for s in stop:
                            if s and s in buffer:
                                out = buffer.split(s)[0]
                                if out:
                                    yield f"data: {out}\n\n"
                                stop_hit = True
                                break
                    if stop_hit:
                        break
                    if new_text:
                        yield f"data: {new_text}\n\n"
            finally:
                yield "data: [DONE]\n\n"
            return

        # llama.cpp streaming if available
        if self.backend_name == "llama_cpp":
            llm = getattr(self.backend, "_llm", None)
            if llm is not None:
                ptxt = f"System: {system_prompt}\nUser: {prompt}\nAssistant:" if system_prompt else prompt
                try:
                    gen = llm.create_completion(
                        prompt=ptxt,
                        temperature=temperature,
                        max_tokens=capped,
                        stop=stop,
                        stream=True,
                    )
                    buffer = ""
                    for ev in gen:
                        chunk = ""
                        try:
                            choices = ev.get("choices") or []
                            if choices:
                                chunk = choices[0].get("text") or ""
                        except Exception:
                            chunk = ""
                        if not chunk:
                            continue
                        buffer += chunk
                        if stop:
                            hit = False
                            for s in stop:
                                if s and s in buffer:
                                    out = buffer.split(s)[0]
                                    if out:
                                        yield f"data: {out}\n\n"
                                    hit = True
                                    break
                            if hit:
                                break
                        yield f"data: {chunk}\n\n"
                except Exception:
                    # fall back to buffered
                    pass
                finally:
                    yield "data: [DONE]\n\n"
                return

        # Fallback: buffered one-shot
        text = self.backend.generate(
            prompt,
            max_new_tokens=capped,
            temperature=temperature,
            system_prompt=system_prompt,
            stop=stop,
        )
        yield f"data: {text}\n\n"
        yield "data: [DONE]\n\n"


model_svc = ModelService()


@app.get("/adapters")
def list_adapters_endpoint(project_id: str):
    sm = _get_db_sessionmaker()
    with sm() as db:
        active = get_active_adapter(db, project_id)
        rows = list_adapters(db, project_id)
        return {
            "active_adapter_id": str(active.id) if active else None,
            "adapters": [
                {
                    "id": str(r.id),
                    "name": r.name,
                    "base_model": r.base_model,
                    "peft_type": r.peft_type,
                    "is_active": bool(r.is_active),
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ],
        }


class ActivatePayload(BaseModel):
    project_id: str
    adapter_id: str


@app.post("/adapters/activate")
def activate_adapter_endpoint(payload: ActivatePayload):
    sm = _get_db_sessionmaker()
    with sm() as db:
        activate_adapter(db, project_id=payload.project_id, adapter_id=payload.adapter_id)
    return {"status": "ok"}


@app.get("/gen/info")
def gen_info():
    # Ensure recommendation resolved
    model_svc._resolve_choice()
    return {
        "hardware": model_svc.hw,
        "backend": model_svc.backend_name,
        "base_model": model_svc.choice.get("base_model") if model_svc.choice else None,
        "quant": model_svc.quant,
        "ctx": model_svc.ctx,
        "max_new_tokens_cap": model_svc.max_new_tokens_cap,
    }


@app.post("/gen/ask")
def gen_ask(payload: AskPayload):
    sm = _get_db_sessionmaker()
    with sm() as db:
        adapter: Adapter | None = None
        adapter_dir: Optional[str] = None
        base_model_override: Optional[str] = None
        if payload.adapter_id:
            adapter = db.get(Adapter, payload.adapter_id)  # type: ignore[arg-type]
        else:
            adapter = get_active_adapter(db, payload.project_id)
        if adapter is None and model_svc.backend_name == "hf":
            raise HTTPException(status_code=404, detail="no adapter active for project")
        if adapter is not None:
            base_model_override = adapter.base_model
            adapter_dir = _download_and_unzip(adapter.artifact_uri)

        # Only HF applies adapters; llama.cpp ignores adapters and uses recommendation/env
        if model_svc.backend_name == "hf":
            model_svc.ensure_loaded(base_model_override=base_model_override, adapter_dir=adapter_dir)
        else:
            model_svc.ensure_loaded()

        text = model_svc.generate(
            payload.prompt,
            max_new_tokens=payload.max_new_tokens or 256,
            temperature=payload.temperature or 0.7,
        )
        out = {
            "text": text,
            "adapter_id": str(adapter.id) if adapter else None,
            "base_model": model_svc.current_base_model,
            "backend": model_svc.backend_name,
        }
        return out


@app.post("/gen/stream")
def gen_stream(payload: AskPayload):
    sm = _get_db_sessionmaker()
    with sm() as db:
        adapter: Adapter | None = None
        adapter_dir: Optional[str] = None
        base_model_override: Optional[str] = None
        if payload.adapter_id:
            adapter = db.get(Adapter, payload.adapter_id)  # type: ignore[arg-type]
        else:
            adapter = get_active_adapter(db, payload.project_id)
        if adapter is None and model_svc.backend_name == "hf":
            raise HTTPException(status_code=404, detail="no adapter active for project")
        if adapter is not None:
            base_model_override = adapter.base_model
            adapter_dir = _download_and_unzip(adapter.artifact_uri)

        if model_svc.backend_name == "hf":
            model_svc.ensure_loaded(base_model_override=base_model_override, adapter_dir=adapter_dir)
        else:
            model_svc.ensure_loaded()

        gen = model_svc.stream(
            payload.prompt,
            max_new_tokens=payload.max_new_tokens or 256,
            temperature=payload.temperature or 0.7,
        )
        return StreamingResponse(gen, media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 9009)))

