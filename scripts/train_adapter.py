from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import uuid
from typing import Any, Dict

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from core.settings import get_settings
from registry.adapters import register_adapter
from registry.storage import put_artifact
from training.data_builders.sft_builder import build_sft_dataset
from training.data_builders.mft_builder import build_mft_dataset
from training.data_builders.orpo_builder import build_pref_dataset
from training.peft_strategies.dora import dora_or_lora_config
from training.peft_strategies.lora import lora_config
from training.peft_strategies.qlora import qlora_config
from training.sft.trainer import train_sft
from training.mft.trainer import train_mft
from training.orpo.trainer import train_orpo


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
    p.add_argument("--output-dir", default=None)
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

    # Train
    out_dir = args.output_dir or os.path.join("./outputs", f"run_{uuid.uuid4().hex[:8]}")
    os.makedirs(out_dir, exist_ok=True)

    if args.mode == "sft":
        metrics = train_sft(
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
        )
    elif args.mode == "mft":
        metrics = train_mft(
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
        )
    else:
        metrics = train_orpo(
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
        )

    # Upload artifact to MinIO and register
    zip_path = zip_dir(out_dir)
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
            metrics=metrics,
            activate=True,
        )
        print({"adapter_id": str(adapter.id), "metrics": metrics, "artifact": s3_uri})


if __name__ == "__main__":
    main()

