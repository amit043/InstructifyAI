from __future__ import annotations

import os
import time
import uuid
from collections import deque
from typing import Any, Iterable, Optional

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.db import get_db
from api.deps import require_curator, require_viewer
from core.settings import get_settings
from models import Dataset, Project
from registry.adapters import TrainingRun
from services.datasets import materialize_dataset_snapshot
from storage.object_store import ObjectStore, create_client
from training.job_runner import get_log_path
from training.tasks import run_training_task
from training.utils import select_training_knobs


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



class TrainingRunResume(BaseModel):
    base_model: Optional[str] = None
    prefer_small: bool = False
    epochs: Optional[int] = None
    lr: Optional[float] = None
    force: bool = False


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
    if dataset is None:
        raise HTTPException(status_code=404, detail="dataset not found")

    store = _get_store()
    if not dataset.snapshot_uri:
        dataset = materialize_dataset_snapshot(db, store, dataset)
        if not dataset.snapshot_uri:
            raise HTTPException(status_code=404, detail="dataset snapshot not found")

    base_model = payload.base_model or os.environ.get("BASE_MODEL") or "microsoft/Phi-3-mini-4k-instruct"
    knobs = select_training_knobs(base_model, payload.prefer_small)

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

    task_config = {
        "project_id": payload.project_id,
        "dataset_id": payload.dataset_id,
        "dataset_snapshot_uri": dataset.snapshot_uri,
        "mode": payload.mode,
        "base_model": base_model,
        "knobs": knobs,
        "epochs": payload.epochs,
        "lr": payload.lr,
    }
    run_training_task.delay(str(run.id), task_config)


    return _serialize_run(run)


@router.post("/runs/{run_id}/resume", response_model=TrainingRunResponse)
def resume_training_run(
    run_id: str,
    payload: TrainingRunResume,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> TrainingRunResponse:
    try:
        rid = uuid.UUID(run_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid run_id")

    run = db.get(TrainingRun, rid)
    if run is None:
        raise HTTPException(status_code=404, detail="not found")

    force_resume = bool(payload.force)
    if run.status == "running" and not force_resume:
        raise HTTPException(status_code=409, detail="run already in progress; retry with force=true to override")
    if not run.input_uri:
        raise HTTPException(status_code=400, detail="missing dataset snapshot")

    dataset = db.execute(
        sa.select(Dataset).where(Dataset.snapshot_uri == run.input_uri)
    ).scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=404, detail="dataset snapshot not found")

    base_model = payload.base_model or run.base_model
    knobs = select_training_knobs(base_model, payload.prefer_small)
    epochs = payload.epochs if payload.epochs is not None else 1
    if epochs <= 0:
        raise HTTPException(status_code=400, detail="epochs must be positive")

    run.base_model = base_model
    run.peft_type = knobs["peft"]
    run.status = "queued"
    run.output_uri = ""
    run.metrics = None
    db.commit()
    db.refresh(run)

    task_config = {
        "project_id": str(run.project_id),
        "dataset_id": str(dataset.id),
        "dataset_snapshot_uri": run.input_uri,
        "mode": run.mode,
        "base_model": base_model,
        "knobs": knobs,
        "epochs": epochs,
    }
    if payload.lr is not None:
        task_config["lr"] = payload.lr
    run_training_task.delay(str(run.id), task_config)

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
    path = get_log_path(rid)
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
    path = get_log_path(rid)
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
