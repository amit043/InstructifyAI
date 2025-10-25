from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import uuid
from typing import Any, Dict, Optional

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from core.settings import get_settings
from registry.adapters import register_adapter
from registry.bindings import register_binding
from registry.model_registry import register_model_route
from registry.storage import put_artifact
from training.data_builders.sft_builder import build_sft_dataset
from training.data_builders.mft_builder import build_mft_dataset
from training.data_builders.orpo_builder import build_pref_dataset
from training.peft_strategies.dora import dora_or_lora_config
from training.peft_strategies.lora import lora_config
from training.peft_strategies.qlora import qlora_config
from training.sft.trainer import TrainResult, train_sft
from training.mft.trainer import train_mft
from training.orpo.trainer import train_orpo


DEFAULT_CHECKPOINT_STEPS = int(os.environ.get("TRAINING_CHECKPOINT_STEPS", "50"))
DEFAULT_CHECKPOINT_LIMIT = int(os.environ.get("TRAINING_CHECKPOINT_LIMIT", "2"))
MANUAL_CKPT_BASENAME = "manual_checkpoint.pt"


def _normalize_checkpoint_path(path: str) -> str:
    resolved = os.path.abspath(path)
    if not os.path.exists(resolved):
        raise FileNotFoundError(f"checkpoint path {resolved} not found")
    return resolved



def _find_checkpoint(output_dir: str, explicit: Optional[str], allow_resume: bool) -> Optional[str]:
    if explicit:
        return _normalize_checkpoint_path(explicit)
    if not allow_resume:
        return None
    if not output_dir or not os.path.isdir(output_dir):
        return None
    ckpt: Optional[str] = None
    try:
        from transformers.trainer_utils import get_last_checkpoint  # type: ignore[import-not-found]

        ckpt = get_last_checkpoint(output_dir)
    except Exception:
        ckpt = None
    if ckpt:
        return ckpt
    manual = os.path.join(output_dir, MANUAL_CKPT_BASENAME)
    if os.path.isfile(manual):
        return manual
    return None


def zip_dir(src_dir: str) -> str:
    base = os.path.abspath(src_dir.rstrip("/\\"))
    out = shutil.make_archive(base, "zip", base)
    return out


def main() -> None:
    p = argparse.ArgumentParser("train_adapter")
    p.add_argument("--mode", choices=["sft", "mft", "orpo"], required=True)
    p.add_argument("--project-id", required=True)
    p.add_argument("--base-model", required=True)
    p.add_argument("--quantization", choices=["int4", "fp16", "fp32"], default="int4")
    p.add_argument("--peft", choices=["dora", "lora", "qlora"], default="dora")
    p.add_argument("--data", required=True, help="Path to JSONL export or pref dataset")
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--batch-size", type=int, default=1)
    p.add_argument("--grad-accum", type=int, default=16)
    p.add_argument("--max-seq-len", type=int, default=2048)
    p.add_argument("--teacher-outputs", default=None)
    p.add_argument("--output-dir", default=None, help="Directory for trainer outputs and artifacts")
    p.add_argument("--document-id", dest="document_id", default=None)
    p.add_argument("--doc-id", dest="document_id", default=None)
    p.add_argument("--model-ref", dest="model_ref", default=None)
    p.add_argument("--tag", dest="binding_tag", default=None)
    p.add_argument("--register-binding", action="store_true")
    p.add_argument("--checkpoint-steps", type=int, default=DEFAULT_CHECKPOINT_STEPS, help="Optimizer steps between checkpoints; 0 disables")
    p.add_argument("--checkpoint-total-limit", type=int, default=DEFAULT_CHECKPOINT_LIMIT, help="How many checkpoints to keep for HF trainers")
    p.add_argument("--resume-from", default=None, help="Explicit checkpoint path to resume from")
    p.add_argument("--no-resume", action="store_true", help="Disable auto-resume from checkpoints in the output dir")
    args = p.parse_args()

    # Build data
    if args.mode == "sft":
        data = build_sft_dataset(input_path=args.data, split_ratio=0.2, max_seq_len=args.max_seq_len)
    elif args.mode == "mft":
        data = build_mft_dataset(
            input_path=args.data, split_ratio=0.2, teacher_outputs_path=args.teacher_outputs
        )
    else:
        data = build_pref_dataset(input_path=args.data)

    # Pick PEFT strategy
    if args.peft == "dora":
        peft_cfg = dora_or_lora_config()
    elif args.peft == "lora":
        peft_cfg = lora_config()
    else:
        peft_cfg = qlora_config()

    out_dir = args.output_dir or os.path.join("./outputs", f"run_{uuid.uuid4().hex[:8]}")
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    resume_checkpoint = _find_checkpoint(out_dir, args.resume_from, not args.no_resume)
    if resume_checkpoint:
        print({"event": "resume", "checkpoint": resume_checkpoint})

    # Train
    if args.mode == "sft":
        train_output = train_sft(
            base_model=args.base_model,
            output_dir=out_dir,
            data=data,
            peft_cfg=peft_cfg,
            quantization=args.quantization,
            max_seq_len=args.max_seq_len,
            lr=args.lr,
            num_epochs=args.epochs,
            batch_size=args.batch_size,
            grad_accum=args.grad_accum,
            checkpoint_steps=args.checkpoint_steps,
            save_total_limit=args.checkpoint_total_limit,
            resume_from_checkpoint=resume_checkpoint,
        )
    elif args.mode == "mft":
        train_output = train_mft(
            base_model=args.base_model,
            output_dir=out_dir,
            data=data,
            peft_cfg=peft_cfg,
            quantization=args.quantization,
            max_seq_len=args.max_seq_len,
            lr=args.lr,
            num_epochs=args.epochs,
            batch_size=args.batch_size,
            grad_accum=args.grad_accum,
            teacher_outputs_path=args.teacher_outputs,
            checkpoint_steps=args.checkpoint_steps,
            save_total_limit=args.checkpoint_total_limit,
            resume_from_checkpoint=resume_checkpoint,
        )
    else:
        train_output = train_orpo(
            base_model=args.base_model,
            output_dir=out_dir,
            pref_data=data,
            peft_cfg=peft_cfg,
            quantization=args.quantization,
            max_seq_len=args.max_seq_len,
            lr=args.lr,
            num_epochs=args.epochs,
            batch_size=args.batch_size,
            grad_accum=args.grad_accum,
            checkpoint_steps=args.checkpoint_steps,
            save_total_limit=args.checkpoint_total_limit,
            resume_from_checkpoint=resume_checkpoint,
            manual_checkpoint_name=MANUAL_CKPT_BASENAME,
        )

    artifact_dir = out_dir
    metrics_payload: Dict[str, Any] | None = None
    if isinstance(train_output, TrainResult):
        artifact_dir = train_output.artifact_dir
        metrics_payload = train_output.metrics
    else:
        metrics_payload = train_output

    if not metrics_payload:
        metrics_payload = {}

    # Upload artifact to MinIO and register
    zip_path = zip_dir(artifact_dir)
    s3_uri = put_artifact(zip_path)

    settings = get_settings()
    engine = sa.create_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with SessionLocal() as db:
        adapter = register_adapter(
            db,
            project_id=args.project_id,
            name=os.path.basename(out_dir),
            base_model=args.base_model,
            peft_type=peft_cfg["type"],
            task_types={"mode": args.mode},
            artifact_uri=s3_uri,
            metrics=metrics_payload,
            activate=True,
        )
        register_model_route(
            db, project_id=args.project_id, adapter_id=str(adapter.id)
        )
        if args.document_id:
            register_model_route(
                db,
                project_id=args.project_id,
                adapter_id=str(adapter.id),
                document_id=args.document_id,
            )

        if args.register_binding:
            if not args.model_ref:
                raise SystemExit("--model-ref is required when --register-binding is set")
            backend_name = (
                os.environ.get("TRAIN_BACKEND")
                or os.environ.get("BASE_BACKEND")
                or "hf"
            )
            binding = register_binding(
                db,
                project_id=args.project_id,
                document_id=args.document_id,
                backend=backend_name,
                base_model=args.base_model,
                adapter_path=out_dir,
                model_ref=args.model_ref,
                tag=args.binding_tag,
            )
            print(
                f"[trainer] registered binding: {binding.model_ref} "
                f"scope=document:{args.document_id}|project:{args.project_id}"
            )

        print({"adapter_id": str(adapter.id), "metrics": metrics_payload, "artifact": s3_uri})


if __name__ == "__main__":
    main()
