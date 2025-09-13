from __future__ import annotations

import os
import tempfile
import zipfile
from functools import lru_cache
from typing import Optional

import sqlalchemy as sa
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker

from core.settings import get_settings
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


@lru_cache()
def _get_backend():
    backend = os.environ.get("BASE_BACKEND", "hf").lower()
    if backend == "rwkv":
        from backends.rwkv_runner import RWKVRunner

        return RWKVRunner()
    if backend == "llama_cpp":
        from backends.llama_cpp_runner import LlamaCppRunner

        return LlamaCppRunner()
    from backends.hf_runner import HFRunner

    return HFRunner()


_LAST = {"adapter_id": None, "base_model": None, "adapter_path": None}


def _ensure_loaded(base_model: str, adapter_local_dir: Optional[str]) -> None:
    backend = _get_backend()
    if _LAST["base_model"] != base_model:
        backend.load_base(base_model, quantization=os.environ.get("QUANT", "int4"))
        _LAST["base_model"] = base_model
        _LAST["adapter_id"] = None
    if adapter_local_dir is not None and _LAST["adapter_id"] != adapter_local_dir:
        backend.load_adapter(adapter_local_dir)
        _LAST["adapter_id"] = adapter_local_dir


def _download_and_unzip(s3_uri: str) -> str:
    tmp = get_artifact(s3_uri)
    # If zip, extract to temp dir
    if zipfile.is_zipfile(tmp):
        d = tempfile.mkdtemp(prefix="adapter_")
        with zipfile.ZipFile(tmp) as z:
            z.extractall(d)
        return d
    return os.path.dirname(tmp)


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


@app.post("/gen/ask")
def gen_ask(payload: AskPayload):
    sm = _get_db_sessionmaker()
    with sm() as db:
        adapter: Adapter | None = None
        if payload.adapter_id:
            # direct fetch
            adapter = db.get(Adapter, payload.adapter_id)  # type: ignore[arg-type]
        else:
            adapter = get_active_adapter(db, payload.project_id)
        if adapter is None:
            raise HTTPException(status_code=404, detail="no adapter active for project")
        base_model = adapter.base_model
        local_dir = _download_and_unzip(adapter.artifact_uri)
        _ensure_loaded(base_model, local_dir)
        backend = _get_backend()
        text = backend.generate(
            payload.prompt,
            max_new_tokens=payload.max_new_tokens or 256,
            temperature=payload.temperature or 0.7,
        )
        return {"text": text, "adapter_id": str(adapter.id), "base_model": base_model}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 9009)))

