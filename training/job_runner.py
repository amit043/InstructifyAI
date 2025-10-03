from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import uuid
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from core.settings import get_settings
from registry.adapters import TrainingRun
from storage.object_store import ObjectStore, create_client
from training.utils import ensure_training_environment_ready

settings = get_settings()
engine = sa.create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _get_store() -> ObjectStore:
    client = create_client(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    return ObjectStore(client=client, bucket=settings.s3_bucket)


def _log_dir() -> str:
    base = os.environ.get("TRAINING_LOG_DIR") or os.path.join(
        os.getcwd(), "outputs", "training", "runs"
    )
    os.makedirs(base, exist_ok=True)
    return base


def get_log_path(run_id: uuid.UUID) -> str:
    return os.path.join(_log_dir(), f"{run_id}.log")





def _run_workspace_dir() -> str:
    base = os.environ.get("TRAINING_RUN_WORKDIR") or os.path.join(
        os.getcwd(), "outputs", "training", "workdirs"
    )
    os.makedirs(base, exist_ok=True)
    return base


def get_run_output_dir(run_id: uuid.UUID) -> str:
    base = _run_workspace_dir()
    path = os.path.join(base, str(run_id))
    os.makedirs(path, exist_ok=True)
    return path



def _clean_metrics(metrics: dict[str, Any] | None) -> dict[str, Any] | None:
    if not metrics:
        return metrics
    cleaned: dict[str, Any] = {}
    for k, v in metrics.items():
        if isinstance(v, float) and math.isnan(v):
            cleaned[k] = None
        else:
            cleaned[k] = v
    return cleaned


def _update_run(
    run_id: uuid.UUID,
    *,
    status: Optional[str] = None,
    metrics: Optional[dict[str, Any]] = None,
    output_uri: Optional[str] = None,
) -> None:
    with SessionLocal() as db:
        run = db.get(TrainingRun, run_id)
        if not run:
            return
        if status is not None:
            run.status = status
        if metrics is not None:
            run.metrics = metrics
        if output_uri is not None:
            run.output_uri = output_uri
        db.commit()


def execute_training_job(run_id: str, config: dict[str, Any]) -> None:
    rid = uuid.UUID(run_id)
    snapshot_uri = config["dataset_snapshot_uri"]
    base_model = config["base_model"]
    knobs = config.get("knobs", {})

    output_dir = get_run_output_dir(rid)

    try:
        ensure_training_environment_ready()
    except RuntimeError as exc:
        _update_run(rid, status="failed")
        raise

    store = _get_store()
    fd, tmp_path = tempfile.mkstemp(prefix="snapshot_", suffix=".jsonl")
    os.close(fd)
    try:
        data = store.get_bytes(snapshot_uri)
        with open(tmp_path, "wb") as handle:
            handle.write(data)
    except Exception as exc:  # noqa: BLE001
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _update_run(rid, status="failed")
        raise RuntimeError(f"failed to download dataset snapshot {snapshot_uri}: {exc}") from exc

    # Prefetch Hugging Face model assets
    if ".gguf" not in base_model.lower():
        try:
            from huggingface_hub import snapshot_download  # type: ignore[import-not-found]

            snapshot_download(
                repo_id=base_model,
                token=os.environ.get("HF_TOKEN"),
                resume_download=True,
                local_files_only=False,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[training] Prefetch failed for {base_model}: {exc}")

    cmd = [
        os.environ.get("PYTHON", "python"),
        os.path.join("scripts", "train_adapter.py"),
        "--mode",
        config["mode"],
        "--project-id",
        config["project_id"],
        "--base-model",
        base_model,
        "--quantization",
        knobs.get("quant", "fp32"),
        "--peft",
        knobs.get("peft", "lora"),
        "--data",
        tmp_path,
        "--output-dir",
        output_dir,
        "--epochs",
        str(config.get("epochs", 1)),
        "--batch-size",
        str(knobs.get("batch_size", 1)),
        "--grad-accum",
        str(knobs.get("grad_accum", 8)),
        "--max-seq-len",
        str(knobs.get("max_seq_len", 1024)),
    ]
    lr = config.get("lr")
    if lr is not None:
        cmd += ["--lr", str(lr)]

    _update_run(rid, status="running")

    last_json: Optional[dict[str, Any]] = None
    log_file = get_log_path(rid)

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        assert proc.stdout is not None

        with open(log_file, "a", encoding="utf-8") as lf:
            lf.write(
                f"[training] run_id={run_id} starting base_model={base_model} peft={knobs.get('peft', 'lora')}\n"
            )
            lf.flush()
            for line in proc.stdout:
                print(line, end="")
                lf.write(line)
                lf.flush()
                payload = line.strip()
                if payload.startswith("{") and payload.endswith("}"):
                    try:
                        candidate = json.loads(payload)
                        if isinstance(candidate, dict) and "artifact" in candidate:
                            last_json = candidate
                    except json.JSONDecodeError:
                        pass

        code = proc.wait()
    except Exception:
        _update_run(rid, status="failed")
        raise
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    if code == 0:
        output_uri = ""
        metrics = None
        if last_json:
            output_uri = last_json.get("artifact") or ""
            metrics = _clean_metrics(last_json.get("metrics"))
        _update_run(rid, status="completed", metrics=metrics, output_uri=output_uri)
    else:
        _update_run(rid, status="failed")
        raise RuntimeError(f"training subprocess exited with code {code}")
