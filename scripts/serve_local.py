from __future__ import annotations

import logging
import os
import time
import threading
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterator, Literal, Optional, Sequence

import sqlalchemy as sa
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, root_validator
from sqlalchemy.orm import sessionmaker

from core.settings import get_settings
from core.hw import detect_hardware
from models.catalog import recommend_for_hw, cap_tokens_for_hw, CATALOG
from registry.adapters import get_active_adapter, list_adapters, activate_adapter, Adapter
from registry.bindings import get_bindings, get_bindings_by_refs
from registry.model_registry import resolve_model_routes
from observability.metrics import (
    GEN_ASK_DURATION,
    GEN_EVIDENCE_RESULTS,
    GEN_VALIDATION_TOTAL,
    GEN_WARM_DURATION,
    GEN_WARM_EVENTS,
)
from registry.storage import ensure_artifact_dir
from retrieval.service import retrieve_evidence


class AskPayload(BaseModel):
    project_id: str
    prompt: str
    max_new_tokens: int | None = None
    temperature: float | None = None
    adapter_id: str | None = None
    document_id: str | None = Field(default=None, description="Document scope (deprecated alias: doc_id)")
    strategy: Literal["first", "vote", "concat", "rerank"] = Field(
        default="first", description="Aggregation strategy when multiple bindings run"
    )
    top_k: int = Field(
        default=2,
        ge=1,
        description="Maximum number of bindings to consider when auto-selecting",
    )
    model_refs: list[str] | None = Field(
        default=None,
        description="Explicit binding model_refs to execute (bypasses registry lookups)",
    )
    include_raw: bool = Field(
        default=False,
        description="Include per-model outputs and metadata without changing the default schema",
    )

    class Config:
        allow_population_by_field_name = True

    @root_validator(pre=True)
    def _normalize_doc_id(cls, values):
        if "document_id" not in values and "doc_id" in values:
            values["document_id"] = values["doc_id"]
            logging.getLogger("serve_local.gen").info(
                "Deprecated parameter 'doc_id' received; mapped to 'document_id'."
            )
        return values


app = FastAPI()
logger = logging.getLogger("serve_local.gen")
_LLAMA_ADAPTER_WARNING_EMITTED = False


@lru_cache()
def _get_db_sessionmaker():
    settings = get_settings()
    engine = sa.create_engine(settings.database_url)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _locate_model_dir(root: str) -> str:
    candidates = ("adapter_config.json", "config.json")
    for name in candidates:
        if os.path.exists(os.path.join(root, name)):
            return root
    for dirpath, _, filenames in os.walk(root):
        for name in candidates:
            if name in filenames:
                return dirpath
    return root


def _download_and_unzip(s3_uri: str) -> str:
    """Materialize an adapter artifact locally and return directory with config."""
    extracted_root = ensure_artifact_dir(s3_uri)
    return _locate_model_dir(extracted_root)


def _resolve_adapter_targets(adapter: Adapter, extracted_dir: str) -> tuple[str, Optional[str]]:
    adapter_cfg = os.path.join(extracted_dir, "adapter_config.json")
    merged_cfg = os.path.join(extracted_dir, "config.json")
    if os.path.exists(adapter_cfg):
        return adapter.base_model, extracted_dir
    if os.path.exists(merged_cfg):
        return extracted_dir, None
    raise HTTPException(status_code=500, detail="adapter artifact missing config files")





class _AdapterChoice:
    __slots__ = ("adapter", "text", "base_model")

    def __init__(self, adapter: Adapter, text: str, base_model: str) -> None:
        self.adapter = adapter
        self.text = text
        self.base_model = base_model


def _aggregate_choices(responses: list[_AdapterChoice]) -> _AdapterChoice:
    if not responses:
        raise HTTPException(status_code=500, detail="no responses to aggregate")
    counts = Counter(choice.text for choice in responses)
    winner_text, _ = counts.most_common(1)[0]
    for choice in responses:
        if choice.text == winner_text:
            return choice
    return responses[0]


@dataclass(frozen=True)
class BindingPlan:
    backend: str
    base_model: str
    adapter_path: str | None
    model_ref: str
    document_id: str | None


def _binding_from_row(row) -> BindingPlan:
    return BindingPlan(
        backend=row.backend,
        base_model=row.base_model,
        adapter_path=row.adapter_path,
        model_ref=row.model_ref,
        document_id=str(row.document_id) if getattr(row, "document_id", None) else None,
    )


def _resolve_binding_plan(db, payload: AskPayload) -> list[BindingPlan]:
    settings = get_settings()
    if not settings.feature_doc_bindings:
        return []

    plans: list[BindingPlan] = []
    if payload.model_refs:
        rows = get_bindings_by_refs(
            db,
            project_id=payload.project_id,
            refs=payload.model_refs,
            document_id=payload.document_id,
        )
        if len(rows) != len(payload.model_refs):
            found = {row.model_ref for row in rows}
            missing = sorted({ref for ref in payload.model_refs if ref not in found})
            raise HTTPException(
                status_code=404, detail=f"model_refs not found: {', '.join(missing)}"
            )
        plans = [_binding_from_row(row) for row in rows]
        return plans

    rows = get_bindings(
        db,
        project_id=payload.project_id,
        document_id=payload.document_id,
        top_k=payload.top_k,
    )
    plans = [_binding_from_row(row) for row in rows]
    if payload.document_id and plans and all(
        plan.document_id != payload.document_id for plan in plans
    ):
        logger.info(
            "doc binding fallback to project scope",
            extra={"project_id": payload.project_id, "document_id": payload.document_id},
        )
    return plans


def _aggregate_binding_texts(responses: list[dict[str, str]], strategy: str) -> str:
    if not responses:
        raise HTTPException(status_code=500, detail="no responses to aggregate")
    texts = [resp.get("text", "") for resp in responses]
    if len(texts) == 1 or strategy == "first":
        return texts[0]
    if strategy == "concat":
        return " ".join(t.strip() for t in texts if t).strip()
    normalized = [t.strip().lower() for t in texts]
    if strategy == "vote":
        counts = Counter(normalized)
        winner, _ = counts.most_common(1)[0]
        candidates = [t for t in texts if t.strip().lower() == winner]
        if candidates:
            return max(candidates, key=len)
        return texts[0]
    if strategy == "rerank":
        return max(texts, key=len)
    raise HTTPException(status_code=400, detail=f"unsupported strategy {strategy}")


GROUNDING_SYSTEM_PROMPT = (
    "You are a precise assistant. Use only the provided context to answer. "
    "Respond succinctly, cite sources using their [chunk_id] identifiers, and do not introduce facts that are not present in the context."
)


def _build_grounded_prompt(
    question: str, evidence: list[dict[str, Any]]
) -> tuple[str, Optional[str], list[dict[str, Any]]]:
    if not evidence:
        settings = get_settings()
        system_prompt = None
        custom = settings.gen_default_prompt
        if custom:
            system_prompt = custom.strip()
        return question, system_prompt, []

    settings = get_settings()
    base_system_prompt = GROUNDING_SYSTEM_PROMPT
    custom_prompt = (settings.gen_default_prompt or "").strip()
    if custom_prompt:
        system_prompt = f"{custom_prompt}\n\n{base_system_prompt}"
    else:
        system_prompt = base_system_prompt

    context_lines: list[str] = []
    citations: list[dict[str, Any]] = []
    for item in evidence:
        chunk_id = item.get("chunk_id")
        if not chunk_id:
            continue
        section_path = item.get("section_path") or []
        if not isinstance(section_path, list):
            section_path = []
        path_str = " / ".join(section_path) if section_path else "Context"
        text = item.get("text", "")
        bullet = f"- [{chunk_id}] {path_str}"
        context_lines.append(bullet)
        context_lines.append(f"  {text}")
        citations.append(
            {
                "chunk_id": chunk_id,
                "doc_id": item.get("doc_id"),
                "section_path": section_path,
                "order": item.get("order"),
                "score": float(item.get("score", 0.0)),
                "rank_score": float(item.get("rank_score", item.get("score", 0.0))),
                "excerpt": text[:500],
            }
        )
    if not context_lines:
        return question, system_prompt, []

    context = "\n".join(context_lines)
    grounded_prompt = (
        f"Context:\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer in at most four sentences and cite sources using [chunk_id]."
    )
    return grounded_prompt, system_prompt, citations


def _answer_references_citations(answer: str, citations: list[dict[str, Any]]) -> bool:
    if not citations:
        return True
    for citation in citations:
        chunk_id = citation.get("chunk_id")
        if chunk_id and f"[{chunk_id}]" in answer:
            return True
    return False


def _enrich_with_citations(body: dict[str, Any], citations: list[dict[str, Any]]) -> None:
    if not citations:
        return
    body["citations"] = citations
    if "answer" in body and not _answer_references_citations(body["answer"], citations):
        body["needs_grounding"] = True


def _warn_llama_adapter(model_ref: str) -> None:
    global _LLAMA_ADAPTER_WARNING_EMITTED
    if not _LLAMA_ADAPTER_WARNING_EMITTED:
        logger.warning("adapter_path ignored for llama_cpp backend", extra={"model_ref": model_ref})
        _LLAMA_ADAPTER_WARNING_EMITTED = True


def _run_binding(
    plan: BindingPlan,
    payload: AskPayload,
    prompt_override: str | None,
    system_prompt: str | None,
    temperature: float,
) -> dict[str, str]:
    adapter_dir = plan.adapter_path if plan.backend == "hf" else None
    if plan.backend != "hf" and plan.adapter_path:
        _warn_llama_adapter(plan.model_ref)
    try:
        model_svc.ensure_loaded(
            base_model_override=plan.base_model,
            adapter_dir=adapter_dir,
            backend_override=plan.backend,
        )
        text = model_svc.generate(
            prompt_override or payload.prompt,
            max_new_tokens=payload.max_new_tokens or 256,
            temperature=temperature,
            system_prompt=system_prompt,
        )
    finally:
        model_svc.clear_backend_override()
    return {"model_ref": plan.model_ref, "text": text}


def _execute_binding_plan(
    plans: Sequence[BindingPlan],
    payload: AskPayload,
    request_id: str | None,
    *,
    prompt_override: str | None = None,
    system_prompt: str | None = None,
    temperature: float,
) -> dict[str, Any]:
    responses = [
        _run_binding(plan, payload, prompt_override, system_prompt, temperature)
        for plan in plans
    ]
    answer = _aggregate_binding_texts(responses, payload.strategy)
    logger.info(
        "gen.ask bindings",
        extra={
            "request_id": request_id,
            "project_id": payload.project_id,
            "document_id": payload.document_id,
            "bindings": [plan.model_ref for plan in plans],
        },
    )
    body: dict[str, Any] = {"answer": answer}
    if payload.include_raw:
        body["raw"] = responses
        body["strategy"] = payload.strategy
        body["used"] = [resp["model_ref"] for resp in responses]
    return body


def _generate_with_adapters(
    adapters: Sequence[Adapter],
    payload: AskPayload,
    grounded_prompt: str,
    system_prompt: Optional[str],
    temperature: float,
) -> dict[str, Any]:
    responses: list[_AdapterChoice] = []
    for adapter in adapters:
        artifact_dir = _download_and_unzip(adapter.artifact_uri)
        base_model_override, adapter_dir_for_load = _resolve_adapter_targets(
            adapter, artifact_dir
        )

        model_svc.ensure_loaded(
            base_model_override=base_model_override, adapter_dir=adapter_dir_for_load
        )
        text = model_svc.generate(
            grounded_prompt,
            max_new_tokens=payload.max_new_tokens or 256,
            temperature=temperature,
            system_prompt=system_prompt,
        )
        current_base = (
            model_svc.current_base_model or base_model_override or adapter.base_model
        )
        responses.append(
            _AdapterChoice(adapter, text, current_base or adapter.base_model)
        )

    primary = _aggregate_choices(responses)
    body: dict[str, Any] = {"answer": primary.text}
    if payload.include_raw:
        raw = [
            {"model_ref": str(choice.adapter.id), "text": choice.text}
            for choice in responses
        ]
        body["raw"] = raw
        body["strategy"] = "vote" if len(responses) > 1 else "first"
        body["used"] = [entry["model_ref"] for entry in raw]
    return body


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
        self._forced_backend_name: Optional[str] = None
        self._active_backend_name: Optional[str] = None

    def _resolve_choice(self) -> None:
        # Lazy hardware detection
        if self.hw is None:
            self.hw = detect_hardware()

        # Env overrides
        base_model_env = os.environ.get("BASE_MODEL")
        backend_env = os.environ.get("BASE_BACKEND", "").lower()
        quant_env = os.environ.get("QUANT")

        backend_choice: Optional[str] = None
        if base_model_env:
            backend_choice = backend_env if backend_env in {"hf", "llama_cpp"} else "hf"
            self.quant = quant_env or ("gguf" if backend_choice == "llama_cpp" else "int4")
            # Context: prefer LLAMA_CTX for llama.cpp; else default
            if backend_choice == "llama_cpp":
                self.ctx = int(os.environ.get("LLAMA_CTX", "4096"))
            else:
                self.ctx = int(os.environ.get("CTX", "4096"))
            self.choice = {
                "backend": backend_choice,
                "base_model": base_model_env,
                "quant": self.quant,
                "ctx": self.ctx,
            }
        else:
            # Recommend based on hardware
            rec = recommend_for_hw(self.hw or {})
            # Respect BASE_BACKEND override even without BASE_MODEL
            if backend_env in {"hf", "llama_cpp"}:
                rec = dict(rec)
                rec["backend"] = backend_env
            self.choice = rec
            backend_choice = rec.get("backend", "hf")
            self.quant = rec.get("quant", "int4")
            self.ctx = int(rec.get("ctx", 4096))
        if self._forced_backend_name:
            backend_choice = self._forced_backend_name
        self.backend_name = backend_choice or "hf"
        if self.choice is None:
            self.choice = {"backend": self.backend_name, "quant": self.quant, "ctx": self.ctx}
        else:
            self.choice["backend"] = self.backend_name

        # If HF backend is selected, ensure base_model is a HF model, not a GGUF path
        if self.backend_name == "hf":
            bm = (self.choice or {}).get("base_model") if self.choice else None
            if isinstance(bm, str) and (bm.endswith(".gguf") or ".gguf" in bm.lower()):
                # Replace with a small HF fallback
                for entry in CATALOG:
                    if entry.get("id") == "phi-3-mini-4k-instruct":
                        self.choice["base_model"] = entry.get("hf_id")
                        break
                self.quant = self.choice.get("quant", "int4")

        # Compute conservative cap
        self.max_new_tokens_cap = cap_tokens_for_hw(self.hw or {}, self.ctx)

        # Instantiate backend if needed
        if self.backend is not None and self._active_backend_name != self.backend_name:
            self.backend = None
        if self.backend is None or self.backend_name not in {"hf", "llama_cpp"}:
            self.backend = None  # reset if invalid

        if self.backend is None:
            if self.backend_name == "llama_cpp":
                from backends.llama_cpp_runner import LlamaCppRunner

                self.backend = LlamaCppRunner()
            else:
                from backends.hf_runner import HFRunner

                self.backend = HFRunner()
            self._active_backend_name = self.backend_name

    def ensure_loaded(
        self,
        base_model_override: Optional[str] = None,
        adapter_dir: Optional[str] = None,
        backend_override: Optional[str] = None,
    ) -> None:
        if backend_override:
            self._forced_backend_name = backend_override
        self._resolve_choice()

        # Decide base model to load
        base_model = base_model_override or (self.choice.get("base_model") if self.choice else None)
        if not base_model:
            raise HTTPException(status_code=500, detail="no base model resolved")

        # If backend/model changed, load base
        if self.current_base_model != base_model:
            try:
                self.backend.load_base(base_model, quantization=self.quant)
                self.current_base_model = base_model
                # reset adapter marker
                self.current_adapter_dir = None
            except ImportError as e:
                # If llama.cpp is unavailable, fall back to HF with a small model
                if self.backend_name == "llama_cpp":
                    # pick a small HF model from catalog
                    fallback = None
                    for e in CATALOG:
                        if e.get("id") == "phi-3-mini-4k-instruct":
                            fallback = e
                            break
                    if not fallback:
                        for e in CATALOG:
                            if e.get("hf_id"):
                                fallback = e
                                break
                    from backends.hf_runner import HFRunner  # lazy import

                    self.backend = HFRunner()
                    self.backend_name = "hf"
                    self._active_backend_name = "hf"
                    self.quant = "int4"
                    fb_model = (fallback or {}).get("hf_id") or base_model
                    self.choice = {"backend": "hf", "base_model": fb_model, "quant": self.quant, "ctx": self.ctx}
                    self.backend.load_base(fb_model, quantization=self.quant)
                    self.current_base_model = fb_model
                    self.current_adapter_dir = None
                else:
                    raise

        # Adapter applies to HF only
        if self.backend_name == "hf" and adapter_dir is not None and self.current_adapter_dir != adapter_dir:
            self.backend.load_adapter(adapter_dir)
            self.current_adapter_dir = adapter_dir

    def clear_backend_override(self) -> None:
        self._forced_backend_name = None

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

def perform_warmup() -> dict[str, Any]:
    """Warm base model and adapters ahead of traffic."""
    settings = get_settings()

    skip = os.environ.get("GEN_SKIP_WARMUP", "").lower() in {"1", "true", "yes"}
    if skip:
        GEN_WARM_EVENTS.labels(status="skipped").inc()
        logger.info("gen warm-up skipped via GEN_SKIP_WARMUP")
        return {"skipped": True}

    start = time.perf_counter()
    warmed_adapters = 0
    base_loaded = False
    errors: list[dict[str, Any]] = []

    try:
        try:
            model_svc.ensure_loaded()
            base_loaded = True
        except Exception as exc:  # pragma: no cover - warmup best-effort
            errors.append({"stage": "base_model", "error": repr(exc)})
            logger.warning("base model warm-up failed", exc_info=True)

        adapter_rows: list[Adapter] = []
        if settings.feature_doc_bindings:
            sm = _get_db_sessionmaker()
            with sm() as db:
                adapter_rows = db.scalars(
                    sa.select(Adapter).where(Adapter.is_active.is_(True))
                ).all()
            limit = settings.max_active_adapters
            if limit and limit > 0:
                adapter_rows = adapter_rows[:limit]

        for adapter in adapter_rows:
            try:
                artifact_dir = _download_and_unzip(adapter.artifact_uri)
                base_model_override, adapter_dir_for_load = _resolve_adapter_targets(
                    adapter, artifact_dir
                )
                model_svc.ensure_loaded(
                    base_model_override=base_model_override,
                    adapter_dir=adapter_dir_for_load,
                )
                warmed_adapters += 1
            except Exception as exc:  # pragma: no cover - warmup best-effort
                errors.append(
                    {"stage": "adapter", "adapter_id": str(adapter.id), "error": repr(exc)}
                )
                logger.warning(
                    "adapter warmup failed",
                    extra={"adapter_id": str(adapter.id), "error": repr(exc)},
                )
    finally:
        model_svc.clear_backend_override()

    duration = time.perf_counter() - start
    try:
        GEN_WARM_DURATION.observe(duration)
    except Exception:
        pass

    status = "success"
    if errors and warmed_adapters == 0 and not base_loaded:
        status = "failed"
    elif errors:
        status = "partial"
    GEN_WARM_EVENTS.labels(status=status).inc()

    logger.info(
        "gen warm-up finished",
        extra={
            "status": status,
            "duration_s": round(duration, 2),
            "base_loaded": base_loaded,
            "warmed_adapters": warmed_adapters,
            "errors": errors[:3],
        },
    )

    return {
        "status": status,
        "base_loaded": base_loaded,
        "warmed_adapters": warmed_adapters,
        "errors": errors,
        "duration": duration,
    }


@app.on_event("startup")
def _warm_on_startup() -> None:
    perform_warmup()

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





def _resolve_adapters_for_payload(db, payload: AskPayload) -> list[Adapter]:
    if payload.adapter_id:
        adapter = db.get(Adapter, payload.adapter_id)  # type: ignore[arg-type]
        if adapter is None:
            raise HTTPException(status_code=404, detail="adapter not found")
        return [adapter]

    import uuid as _uuid

    try:
        _uuid.UUID(payload.project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")

    adapters: list[Adapter] = []
    routes = resolve_model_routes(
        db, project_id=payload.project_id, document_id=payload.document_id
    )
    for route in routes:
        adapter = db.get(Adapter, route.adapter_id)  # type: ignore[arg-type]
        if adapter is not None:
            adapters.append(adapter)

    if not adapters:
        adapter = get_active_adapter(db, payload.project_id)
        if adapter is not None:
            adapters.append(adapter)

    if not adapters:
        raise HTTPException(status_code=404, detail="no adapter active for project")
    return adapters


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
def gen_ask(payload: AskPayload, request: Request):
    start_time = time.perf_counter()
    request_id = request.headers.get("x-request-id") or request.headers.get("X-Request-ID")
    model_svc.clear_backend_override()
    model_svc._resolve_choice()
    settings = get_settings()
    fallback_answer = settings.gen_fallback_answer
    allow_retry = bool(settings.gen_retry_on_missing_citations)

    try:
        sm = _get_db_sessionmaker()
        with sm() as db:
            evidence = retrieve_evidence(
                db,
                project_id=payload.project_id,
                document_id=payload.document_id,
                prompt=payload.prompt,
            )
            min_rank = settings.gen_min_rank_score or 0.0
            if evidence and min_rank > 0:
                evidence = [
                    item
                    for item in evidence
                    if float(item.get("rank_score", item.get("score", 0.0))) >= min_rank
                ]
            grounded_prompt, system_prompt, citations = _build_grounded_prompt(
                payload.prompt, evidence
            )
            plans = _resolve_binding_plan(db, payload)
            adapters: list[Adapter] = []
            if not plans and model_svc.backend_name != "llama_cpp":
                adapters = _resolve_adapters_for_payload(db, payload)

        base_temperature = (
            payload.temperature if payload.temperature is not None else 0.7
        )

        def _generate_once(temperature: float) -> dict[str, Any]:
            if plans:
                return _execute_binding_plan(
                    plans,
                    payload,
                    request_id,
                    prompt_override=grounded_prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                )

            if model_svc.backend_name == "llama_cpp":
                model_svc.ensure_loaded()
                text = model_svc.generate(
                    grounded_prompt,
                    max_new_tokens=payload.max_new_tokens or 256,
                    temperature=temperature,
                    system_prompt=system_prompt,
                )
                body: dict[str, Any] = {"answer": text}
                if payload.include_raw:
                    raw = [
                        {"model_ref": model_svc.backend_name or "llama_cpp", "text": text}
                    ]
                    body["raw"] = raw
                    body["strategy"] = "first"
                    body["used"] = [raw[0]["model_ref"]]
                return body

            if not adapters:
                raise HTTPException(status_code=404, detail="no adapter active for project")

            return _generate_with_adapters(
                adapters, payload, grounded_prompt, system_prompt, temperature
            )

        body = _generate_once(base_temperature)
        _enrich_with_citations(body, citations)

        outcome = "pass"
        citations_list = body.get("citations", [])
        has_citations = _answer_references_citations(
            body.get("answer", ""), citations_list
        )

        if not citations:
            outcome = "no_evidence"
            original_answer = body.get("answer")
            body = dict(body)
            body["answer"] = fallback_answer
            body["needs_grounding"] = True
            body["fallback_reason"] = "no_evidence"
            if original_answer:
                body["original_answer"] = original_answer
            body.setdefault("citations", [])
        elif not has_citations:
            if allow_retry:
                retry_body = _generate_once(0.0)
                _enrich_with_citations(retry_body, citations)
                if _answer_references_citations(
                    retry_body.get("answer", ""), retry_body.get("citations", [])
                ):
                    body = retry_body
                    outcome = "retry_success"
                else:
                    original_answer = retry_body.get("answer")
                    fallback_body = dict(retry_body)
                    fallback_body["answer"] = fallback_answer
                    fallback_body["needs_grounding"] = True
                    fallback_body["fallback_reason"] = "missing_citation"
                    if original_answer:
                        fallback_body["original_answer"] = original_answer
                    body = fallback_body
                    outcome = "fallback"
            else:
                original_answer = body.get("answer")
                body = dict(body)
                body["answer"] = fallback_answer
                body["needs_grounding"] = True
                body["fallback_reason"] = "missing_citation"
                if original_answer:
                    body["original_answer"] = original_answer
                outcome = "fallback"

        try:
            GEN_VALIDATION_TOTAL.labels(outcome=outcome).inc()
        except Exception:
            pass

        return body
    finally:
        duration = time.perf_counter() - start_time
        try:
            GEN_ASK_DURATION.observe(duration)
        except Exception:
            pass


@app.post("/gen/stream")
def gen_stream(payload: AskPayload):
    # Resolve first; skip adapters for llama.cpp
    model_svc._resolve_choice()
    sm = _get_db_sessionmaker()
    with sm() as db:
        evidence = retrieve_evidence(
            db,
            project_id=payload.project_id,
            document_id=payload.document_id,
            prompt=payload.prompt,
        )
    grounded_prompt, system_prompt, _ = _build_grounded_prompt(payload.prompt, evidence)

    if model_svc.backend_name == "llama_cpp":
        model_svc.ensure_loaded()
        gen = model_svc.stream(
            grounded_prompt,
            max_new_tokens=payload.max_new_tokens or 256,
            temperature=payload.temperature or 0.7,
            system_prompt=system_prompt,
        )
        return StreamingResponse(gen, media_type="text/event-stream")

    with sm() as db:
        adapters = _resolve_adapters_for_payload(db, payload)
        adapter = adapters[0]
        artifact_dir = _download_and_unzip(adapter.artifact_uri)
        base_model_override, adapter_dir_for_load = _resolve_adapter_targets(adapter, artifact_dir)

        model_svc.ensure_loaded(
            base_model_override=base_model_override, adapter_dir=adapter_dir_for_load
        )
        gen = model_svc.stream(
            grounded_prompt,
            max_new_tokens=payload.max_new_tokens or 256,
            temperature=payload.temperature or 0.7,
            system_prompt=system_prompt,
        )
        return StreamingResponse(gen, media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 9009)))
