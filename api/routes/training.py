from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import uuid
from typing import Any, Dict, Optional, Iterable
import time
from collections import deque

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from api.db import get_db
from api.deps import require_curator, require_viewer
from core.hw import detect_hardware
from core.settings import get_settings
from models import Dataset, Project
from registry.adapters import TrainingRun
from storage.object_store import ObjectStore, create_client


router = APIRouter(prefix="/training", tags=["training"])


def _get_store() -> ObjectStore:
    settings = get_settings()
    client = create_client(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    return ObjectStore(client=client, bucket=settings.s3_bucket)


class TrainingRunCreate(BaseModel):
    project_id: str
    dataset_id: str
    mode: str  # "sft" | "mft" | "orpo"
    base_model: Optional[str] = None
    prefer_small: bool = False
    epochs: int = 1
    lr: Optional[float] = None


class TrainingRunResponse(BaseModel):
    id: str
    project_id: str
    mode: str
    base_model: str
    peft_type: str
    input_uri: str
    output_uri: Optional[str] = None
    status: str
    metrics: Optional[dict[str, Any]] = None
    created_at: str


def _log_dir() -> str:
    base = os.environ.get("TRAINING_LOG_DIR") or os.path.join(os.getcwd(), "outputs", "training", "runs")
    os.makedirs(base, exist_ok=True)
    return base


def _log_path(run_id: uuid.UUID) -> str:
    return os.path.join(_log_dir(), f"{run_id}.log")


def _serialize_run(r: TrainingRun) -> TrainingRunResponse:
    return TrainingRunResponse(
        id=str(r.id),
        project_id=str(r.project_id),
        mode=r.mode,
        base_model=r.base_model,
        peft_type=r.peft_type,
        input_uri=r.input_uri,
        output_uri=r.output_uri,
        status=r.status,
        metrics=r.metrics or None,
        created_at=r.created_at.isoformat(),
    )


def _choose_training_knobs(base_model: Optional[str], prefer_small: bool, ctx_hint: int = 4096) -> Dict[str, Any]:
    hw = detect_hardware()
    has_cuda = bool(hw.get("has_cuda", False))
    vram_mb = hw.get("vram_mb")
    vram_mb = int(vram_mb) if isinstance(vram_mb, (int, float)) else None

    peft = "lora"
    quant = "fp32"
    batch_size = 1
    grad_accum = 8
    max_seq_len = min(1024, ctx_hint)

    if has_cuda and (vram_mb or 0) >= 16000:
        peft = "dora"
        quant = "fp16"
        batch_size = 2
        grad_accum = 8
        max_seq_len = min(4096, ctx_hint)
    elif has_cuda and (vram_mb or 0) >= 8000:
        peft = "qlora"
        quant = "int4"
        batch_size = 1
        grad_accum = 16
        max_seq_len = min(2048, ctx_hint)

    return {
        "peft": peft,
        "quant": quant,
        "batch_size": batch_size,
        "grad_accum": grad_accum,
        "max_seq_len": max_seq_len,
    }


def _run_training_thread(
    *,
    run_id: uuid.UUID,
    payload: TrainingRunCreate,
    tmp_path: str,
    base_model: str,
    knobs: Dict[str, Any],
) -> None:
    settings = get_settings()
    engine = sa.create_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with SessionLocal() as db:
        # mark running
        r = db.get(TrainingRun, run_id)
        if not r:
            return
        r.status = "running"
        db.commit()

    # Prefetch HF model into cache to avoid long first-run delays
    if ".gguf" not in base_model.lower():
        try:
            from huggingface_hub import snapshot_download  # type: ignore

            print(f"[training] Prefetching base model: {base_model}")
            snapshot_download(repo_id=base_model, token=os.environ.get("HF_TOKEN"), resume_download=True)
        except Exception as e:
            print(f"[training] Prefetch failed for {base_model}: {e}")

    cmd = [
        os.environ.get("PYTHON", "python"),
        os.path.join("scripts", "train_adapter.py"),
        "--mode",
        payload.mode,
        "--project-id",
        payload.project_id,
        "--base-model",
        base_model,
        "--quantization",
        knobs["quant"],
        "--peft",
        knobs["peft"],
        "--data",
        tmp_path,
        "--epochs",
        str(payload.epochs),
        "--batch-size",
        str(knobs["batch_size"]),
        "--grad-accum",
        str(knobs["grad_accum"]),
        "--max-seq-len",
        str(knobs["max_seq_len"]),
    ]
    if payload.lr is not None:
        cmd += ["--lr", str(payload.lr)]

    # stream subprocess output and capture last JSON line
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    last_json: Optional[dict] = None
    assert proc.stdout is not None
    log_file = _log_path(run_id)
    with open(log_file, "a", encoding="utf-8") as lf:
        lf.write(f"[training] run_id={run_id} starting with base_model={base_model} peft={knobs['peft']}\n")
        lf.flush()
        for line in proc.stdout:
            print(line, end="")  # forward logs
            lf.write(line)
            lf.flush()
            l = line.strip()
            if l.startswith("{") and l.endswith("}"):
                try:
                    obj = json.loads(l)
                    if isinstance(obj, dict) and "artifact" in obj:
                        last_json = obj
                except Exception:
                    pass
    code = proc.wait()

    with SessionLocal() as db:
        r = db.get(TrainingRun, run_id)
        if not r:
            return
        if code == 0:
            r.status = "completed"
            if last_json:
                r.output_uri = last_json.get("artifact") or ""
                try:
                    r.metrics = last_json.get("metrics")
                except Exception:
                    pass
        else:
            r.status = "failed"
        db.commit()
    with open(log_file, "a", encoding="utf-8") as lf:
        lf.write(f"[training] run_id={run_id} finished status={'completed' if code == 0 else 'failed'}\n")
        lf.flush()


@router.post("/runs", response_model=TrainingRunResponse)
def create_training_run(
    payload: TrainingRunCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> TrainingRunResponse:
    # validate ids
    try:
        proj_uuid = uuid.UUID(payload.project_id)
        ds_uuid = uuid.UUID(payload.dataset_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid ids")

    project = db.get(Project, proj_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    dataset = db.get(Dataset, ds_uuid)
    if dataset is None or dataset.snapshot_uri is None:
        raise HTTPException(status_code=404, detail="dataset snapshot not found")

    # fetch dataset snapshot to a temp file accessible to this container
    store = _get_store()
    data = store.get_bytes(dataset.snapshot_uri)
    fd, tmp_path = tempfile.mkstemp(prefix="snapshot_", suffix=".jsonl")
    os.close(fd)
    with open(tmp_path, "wb") as f:
        f.write(data)

    # choose base model & knobs
    base_model = payload.base_model or os.environ.get("BASE_MODEL") or "microsoft/Phi-3-mini-4k-instruct"
    knobs = _choose_training_knobs(base_model, payload.prefer_small)

    # persist run
    run = TrainingRun(
        project_id=proj_uuid,
        mode=payload.mode,
        base_model=base_model,
        peft_type=knobs["peft"],
        input_uri=dataset.snapshot_uri,
        output_uri="",
        status="queued",
        metrics=None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # launch in background thread
    t = threading.Thread(
        target=_run_training_thread,
        kwargs=dict(run_id=run.id, payload=payload, tmp_path=tmp_path, base_model=base_model, knobs=knobs),
        daemon=True,
    )
    t.start()

    return _serialize_run(run)


@router.get("/runs", response_model=list[TrainingRunResponse])
def list_training_runs(
    project_id: Optional[str] = None,
    db: Session = Depends(get_db),
    _: str = Depends(require_viewer),
) -> list[TrainingRunResponse]:
    stmt = sa.select(TrainingRun)
    if project_id:
        try:
            pid = uuid.UUID(project_id)
        except Exception:
            raise HTTPException(status_code=400, detail="invalid project_id")
        stmt = stmt.where(TrainingRun.project_id == pid)
    rows = db.scalars(stmt.order_by(TrainingRun.created_at.desc())).all()
    return [_serialize_run(r) for r in rows]


@router.get("/runs/{run_id}", response_model=TrainingRunResponse)
def get_training_run(
    run_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_viewer),
) -> TrainingRunResponse:
    try:
        rid = uuid.UUID(run_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid run_id")
    run = db.get(TrainingRun, rid)
    if run is None:
        raise HTTPException(status_code=404, detail="not found")
    return _serialize_run(run)


@router.get("/runs/{run_id}/logs", response_class=PlainTextResponse)
def get_training_run_logs(
    run_id: str,
    tail: int = 200,
    db: Session = Depends(get_db),
    _: str = Depends(require_viewer),
) -> PlainTextResponse:
    try:
        rid = uuid.UUID(run_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid run_id")
    run = db.get(TrainingRun, rid)
    if run is None:
        raise HTTPException(status_code=404, detail="not found")
    path = _log_path(rid)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="log not found yet")
    if tail and tail > 0:
        lines = deque(maxlen=min(tail, 5000))
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for ln in f:
                lines.append(ln)
        body = "".join(lines)
    else:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            body = f.read()
    return PlainTextResponse(content=body)


def _sse_format(line: str) -> str:
    line = line.rstrip("\n")
    return f"data: {line}\n\n"


@router.get("/runs/{run_id}/logs/stream")
def stream_training_run_logs(
    run_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_viewer),
):
    try:
        rid = uuid.UUID(run_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid run_id")
    path = _log_path(rid)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="log not found yet")

    def tail_file() -> Iterable[bytes]:
        last_pos = 0
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                last_pos = f.tell()
        except FileNotFoundError:
            yield _sse_format("log file disappeared").encode()
            return
        idle_loops = 0
        while True:
            try:
                with open(path, "rb") as f:
                    f.seek(last_pos)
                    chunk = f.read()
                    if chunk:
                        idle_loops = 0
                        last_pos = f.tell()
                        for ln in chunk.decode(errors="ignore").splitlines():
                            yield _sse_format(ln).encode()
                    else:
                        idle_loops += 1
            except FileNotFoundError:
                yield _sse_format("log file not found").encode()
                break

            run = db.get(TrainingRun, rid)
            if run and run.status in ("completed", "failed") and idle_loops >= 3:
                break
            time.sleep(1.0)

    return StreamingResponse(tail_file(), media_type="text/event-stream")
