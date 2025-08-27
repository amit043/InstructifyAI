import uuid
from dataclasses import dataclass
from typing import List

import boto3  # type: ignore[import-untyped]
from botocore.client import BaseClient  # type: ignore[import-untyped]
from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.settings import get_settings
from models import Dataset, Document

RAW_PREFIX = "raw"
DERIVED_PREFIX = "derived"
EXPORTS_PREFIX = "exports"
FIGURES_SUBPATH = "figures"


def raw_key(doc_id: str, filename: str) -> str:
    return f"{RAW_PREFIX}/{doc_id}/{filename}"


def raw_bundle_key(doc_id: str) -> str:
    return raw_key(doc_id, "bundle.zip")


def derived_key(doc_id: str, filename: str) -> str:
    return f"{DERIVED_PREFIX}/{doc_id}/{filename}"


def figure_key(doc_id: str, filename: str) -> str:
    """Location for derived figure images."""
    return derived_key(doc_id, f"{FIGURES_SUBPATH}/{filename}")


def export_key(export_id: str, filename: str) -> str:
    return f"{EXPORTS_PREFIX}/{export_id}/{filename}"


def dataset_snapshot_key(dataset_id: str) -> str:
    return f"{DERIVED_PREFIX}/datasets/{dataset_id}/snapshot.jsonl"


def dataset_csv_key(dataset_id: str) -> str:
    return f"{DERIVED_PREFIX}/datasets/{dataset_id}/snapshot.csv"


def validation_report_key(dataset_id: str, report_id: str) -> str:
    return f"{DERIVED_PREFIX}/datasets/{dataset_id}/validation/{report_id}.json"


def create_client(
    *, endpoint: str, access_key: str, secret_key: str, secure: bool = False
) -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=("https://" if secure else "http://") + endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )


@dataclass
class ObjectStore:
    client: BaseClient
    bucket: str

    def put_bytes(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def get_bytes(self, key: str) -> bytes:
        resp = self.client.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read()

    def list(self, prefix: str) -> List[str]:
        resp = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        return sorted(obj["Key"] for obj in resp.get("Contents", []))

    def presign_get(self, key: str, expiry: int) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expiry
        )

    def presign_put(self, key: str, expiry: int) -> str:
        return self.client.generate_presigned_url(
            "put_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expiry
        )


def signed_url(
    store: "ObjectStore",
    key: str,
    *,
    db: Session | None = None,
    project_id: str | None = None,
    expiry: int | None = None,
) -> str:
    """Generate a presigned GET URL using settings for expiry.

    If ``db`` and ``project_id`` are provided, enforce that ``key`` belongs to
    the given project before generating the URL.
    """
    if db is not None and project_id is not None:
        parts = key.split("/")
        if parts and parts[0] in {RAW_PREFIX, DERIVED_PREFIX} and len(parts) > 1:
            if parts[0] == DERIVED_PREFIX and parts[1] == "datasets" and len(parts) > 2:
                try:
                    ds_uuid = uuid.UUID(parts[2])
                except Exception:
                    raise HTTPException(status_code=403, detail="forbidden")
                dataset = db.get(Dataset, ds_uuid)
                if dataset is None or str(dataset.project_id) != project_id:
                    raise HTTPException(status_code=403, detail="forbidden")
            else:
                doc = db.get(Document, parts[1])
                if doc is None or str(doc.project_id) != project_id:
                    raise HTTPException(status_code=403, detail="forbidden")
    settings = get_settings()
    exp = expiry or settings.export_signed_url_expiry_seconds
    return store.presign_get(key, exp)


__all__ = [
    "ObjectStore",
    "create_client",
    "raw_key",
    "raw_bundle_key",
    "derived_key",
    "figure_key",
    "export_key",
    "dataset_snapshot_key",
    "dataset_csv_key",
    "validation_report_key",
    "signed_url",
]
