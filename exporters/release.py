from __future__ import annotations

import hashlib
import json
import uuid
from typing import Dict, List, Tuple

import sqlalchemy as sa
from sqlalchemy.orm import Session

from models import Chunk, Document, Release
from storage.object_store import ObjectStore, derived_key, export_key, signed_url


def build_manifest(db: Session, project_id: uuid.UUID) -> dict:
    """Collect documents and chunk hashes for a project."""
    docs = db.scalars(
        sa.select(Document).where(Document.project_id == project_id)
    ).all()
    manifest_docs: List[dict] = []
    for doc in docs:
        dv = doc.latest_version
        if dv is None:
            continue
        chunks = db.scalars(
            sa.select(Chunk).where(
                Chunk.document_id == doc.id, Chunk.version == dv.version
            )
        ).all()
        manifest_docs.append(
            {
                "id": doc.id,
                "doc_hash": dv.doc_hash,
                "chunks": {ch.id: ch.text_hash for ch in chunks},
            }
        )
    manifest_docs.sort(key=lambda d: d["id"])
    return {"project_id": str(project_id), "documents": manifest_docs}


def manifest_hash(manifest: dict) -> str:
    payload = json.dumps(manifest, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def diff_manifests(base: dict, compare: dict) -> dict:
    """Return added/removed/changed docs and chunks between two manifests."""
    docs1 = {d["id"]: d for d in base.get("documents", [])}
    docs2 = {d["id"]: d for d in compare.get("documents", [])}
    added_docs = sorted(set(docs2) - set(docs1))
    removed_docs = sorted(set(docs1) - set(docs2))
    changed: Dict[str, Dict[str, List[str] | bool]] = {}
    for doc_id in set(docs1) & set(docs2):
        d1, d2 = docs1[doc_id], docs2[doc_id]
        if d1["doc_hash"] != d2["doc_hash"]:
            changed[doc_id] = {"doc_hash_changed": True}
            continue
        c1 = d1.get("chunks", {})
        c2 = d2.get("chunks", {})
        add_c = sorted(set(c2) - set(c1))
        rem_c = sorted(set(c1) - set(c2))
        chg_c = sorted([cid for cid in set(c1) & set(c2) if c1[cid] != c2[cid]])
        if add_c or rem_c or chg_c:
            changed[doc_id] = {
                "added": add_c,
                "removed": rem_c,
                "changed": chg_c,
            }
    return {"added": added_docs, "removed": removed_docs, "changed": changed}


def export_release(store: ObjectStore, release: Release) -> Tuple[str, str]:
    """Materialize a release export and return presigned URL."""
    lines: List[str] = []
    for doc in release.manifest.get("documents", []):
        key = derived_key(doc["id"], "chunks.jsonl")
        try:
            data = store.get_bytes(key).decode("utf-8").strip()
        except Exception:
            data = ""
        if data:
            lines.append(data)
    payload = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    data_key = export_key(str(release.id), "data.jsonl")
    manifest_key = export_key(str(release.id), "manifest.json")
    store.put_bytes(data_key, payload)
    store.put_bytes(
        manifest_key, json.dumps(release.manifest, sort_keys=True).encode("utf-8")
    )
    url = signed_url(store, data_key)
    return str(release.id), url


__all__ = [
    "build_manifest",
    "manifest_hash",
    "diff_manifests",
    "export_release",
]
