from dataclasses import dataclass
from typing import List

import boto3  # type: ignore[import-untyped]
from botocore.client import BaseClient  # type: ignore[import-untyped]

RAW_PREFIX = "raw"
DERIVED_PREFIX = "derived"
EXPORTS_PREFIX = "exports"


def raw_key(doc_id: str, filename: str) -> str:
    return f"{RAW_PREFIX}/{doc_id}/{filename}"


def derived_key(doc_id: str, filename: str) -> str:
    return f"{DERIVED_PREFIX}/{doc_id}/{filename}"


def export_key(export_id: str, filename: str) -> str:
    return f"{EXPORTS_PREFIX}/{export_id}/{filename}"


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


__all__ = [
    "ObjectStore",
    "create_client",
    "raw_key",
    "derived_key",
    "export_key",
]
