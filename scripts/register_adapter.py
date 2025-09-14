from __future__ import annotations

import argparse
import os
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from core.settings import get_settings
from registry.adapters import register_adapter


def main() -> None:
    p = argparse.ArgumentParser("register_adapter")
    p.add_argument("--project-id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--base-model", required=True)
    p.add_argument("--peft", choices=["dora", "lora", "qlora", "rwkv_state"], required=True)
    p.add_argument("--artifact", required=True, help="s3:// URI or local path already uploaded")
    p.add_argument("--activate", action="store_true")
    args = p.parse_args()

    settings = get_settings()
    engine = sa.create_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with SessionLocal() as db:
        ad = register_adapter(
            db,
            project_id=args.project_id,
            name=args.name,
            base_model=args.base_model,
            peft_type=args.peft,
            task_types={},
            artifact_uri=args.artifact,
            metrics=None,
            activate=args.activate,
        )
        print({"adapter_id": str(ad.id)})


if __name__ == "__main__":
    main()

