from __future__ import annotations

import os
import tempfile
import uuid
from typing import Tuple

from core.settings import get_settings
from storage.object_store import ObjectStore, create_client


def _get_store() -> ObjectStore:
    s = get_settings()
    client = create_client(
        endpoint=s.minio_endpoint,
        access_key=s.minio_access_key,
        secret_key=s.minio_secret_key,
        secure=s.minio_secure,
    )
    return ObjectStore(client=client, bucket=s.s3_bucket)


def _artifact_key(artifact_id: str, filename: str) -> str:
    return f"adapters/{artifact_id}/{filename}"


def put_artifact(local_path: str) -> str:
    """Upload a local file to object storage and return an s3:// URI."""
    store = _get_store()
    art_id = str(uuid.uuid4())
    filename = os.path.basename(local_path)
    key = _artifact_key(art_id, filename)
    with open(local_path, "rb") as f:
        store.put_bytes(key, f.read())
    s = get_settings()
    return f"s3://{s.s3_bucket}/{key}"


def get_artifact(s3_uri: str) -> str:
    """Download an artifact referenced by s3://bucket/key to a temp path and return it."""
    store = _get_store()
    assert s3_uri.startswith("s3://"), "invalid s3 uri"
    _, rest = s3_uri.split("s3://", 1)
    bucket, key = rest.split("/", 1)
    if bucket != store.bucket:
        # Cross-bucket not supported in this helper
        raise ValueError("artifact bucket mismatch")
    data = store.get_bytes(key)
    fd, tmp = tempfile.mkstemp(prefix="artifact_", suffix="_" + os.path.basename(key))
    os.close(fd)
    with open(tmp, "wb") as f:
        f.write(data)
    return tmp


__all__ = ["put_artifact", "get_artifact"]

