from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any
import uuid
import zipfile

from core.settings import get_settings
from observability.metrics import ADAPTER_CACHE_EVENTS
from storage.object_store import ObjectStore, create_client

CACHE_META_FILENAME = "meta.json"
EXTRACTED_DIRNAME = "extracted"


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


def _cache_root() -> Path:
    settings = get_settings()
    base = settings.adapter_cache_dir or os.environ.get("ADAPTER_CACHE_DIR")
    if base:
        root = Path(base)
    else:
        root = Path(tempfile.gettempdir()) / "instructify_adapters"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cache_dir_for_uri(s3_uri: str) -> Path:
    digest = hashlib.sha256(s3_uri.encode("utf-8")).hexdigest()
    cache_dir = _cache_root() / digest
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _meta_path(cache_dir: Path) -> Path:
    return cache_dir / CACHE_META_FILENAME


def _read_meta(cache_dir: Path) -> dict[str, Any] | None:
    meta_path = _meta_path(cache_dir)
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text())
    except Exception:
        return None


def _write_meta(cache_dir: Path, meta: dict[str, Any]) -> None:
    tmp = cache_dir / (CACHE_META_FILENAME + ".tmp")
    tmp.write_text(json.dumps(meta))
    tmp.replace(_meta_path(cache_dir))


def ensure_cached_artifact(s3_uri: str, *, force_refresh: bool = False) -> Path:
    """Ensure the artifact referenced by s3:// URI exists locally and return its path."""
    if not s3_uri.startswith("s3://"):
        raise ValueError("invalid s3 uri")
    cache_dir = _cache_dir_for_uri(s3_uri)
    meta = _read_meta(cache_dir) if not force_refresh else None
    filename = None
    if meta and meta.get("s3_uri") == s3_uri:
        filename = meta.get("filename")
        if filename:
            cached = cache_dir / filename
            if cached.exists():
                try:
                    ADAPTER_CACHE_EVENTS.labels(event="hit").inc()
                except Exception:
                    pass
                return cached

    store = _get_store()
    _, rest = s3_uri.split("s3://", 1)
    bucket, key = rest.split("/", 1)
    if bucket != store.bucket:
        raise ValueError("artifact bucket mismatch")

    data = store.get_bytes(key)
    filename = os.path.basename(key)
    tmp_path = cache_dir / f"{filename}.download"
    tmp_path.write_bytes(data)
    final_path = cache_dir / filename
    tmp_path.replace(final_path)
    _write_meta(cache_dir, {"s3_uri": s3_uri, "filename": filename, "size": len(data)})
    try:
        ADAPTER_CACHE_EVENTS.labels(event="miss").inc()
    except Exception:
        pass
    return final_path


def ensure_artifact_dir(s3_uri: str) -> Path:
    """Return a stable directory containing the artifact's usable files."""
    cached_file = ensure_cached_artifact(s3_uri)
    cache_dir = cached_file.parent
    extracted_dir = cache_dir / EXTRACTED_DIRNAME
    marker = extracted_dir / ".complete"

    if zipfile.is_zipfile(cached_file):
        if marker.exists() and extracted_dir.exists():
            try:
                ADAPTER_CACHE_EVENTS.labels(event="extract_hit").inc()
            except Exception:
                pass
            return extracted_dir
        temp_extract = Path(tempfile.mkdtemp(prefix="adapter_extract_", dir=str(_cache_root())))
        try:
            with zipfile.ZipFile(cached_file) as zf:
                zf.extractall(temp_extract)
            if extracted_dir.exists():
                shutil.rmtree(extracted_dir)
            shutil.move(str(temp_extract), extracted_dir)
            marker.touch()
        finally:
            if temp_extract.exists():
                shutil.rmtree(temp_extract, ignore_errors=True)
        try:
            ADAPTER_CACHE_EVENTS.labels(event="extract_miss").inc()
        except Exception:
            pass
        return extracted_dir

    # Non-zip artifacts live alongside the cached file
    if not extracted_dir.exists():
        extracted_dir.mkdir(parents=True, exist_ok=True)
    target = extracted_dir / cached_file.name
    if not target.exists():
        shutil.copy2(cached_file, target)
        try:
            ADAPTER_CACHE_EVENTS.labels(event="extract_miss").inc()
        except Exception:
            pass
    else:
        try:
            ADAPTER_CACHE_EVENTS.labels(event="extract_hit").inc()
        except Exception:
            pass
    marker.touch()
    return extracted_dir


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
    """Return the path to a cached artifact (backwards-compatible helper)."""
    return str(ensure_cached_artifact(s3_uri))


__all__ = ["put_artifact", "get_artifact", "ensure_cached_artifact", "ensure_artifact_dir"]
