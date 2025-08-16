import csv
import hashlib
import io
import json
import subprocess
from datetime import datetime
from typing import Dict, Iterable, List, Tuple

from storage.object_store import ObjectStore, derived_key, export_key

from .templates import compile_template

RAG_TEMPLATE = '{{ {"context": ((chunk.source.section_path | join(" / ")) ~ ": " ~ chunk.content.text), "answer": ""} | tojson }}'


def _get_template(template: str | None, preset: str | None) -> str:
    if preset:
        if preset == "rag":
            return RAG_TEMPLATE
        raise ValueError("unknown preset")
    if template is None:
        raise ValueError("template or preset required")
    return template


def _load_chunks(store: ObjectStore, doc_ids: List[str]) -> Iterable[dict]:
    for doc_id in doc_ids:
        data = (
            store.get_bytes(derived_key(doc_id, "chunks.jsonl")).decode("utf-8").strip()
        )
        if not data:
            continue
        for line in data.splitlines():
            yield json.loads(line)


def _compute_export_id(
    fmt: str,
    doc_ids: List[str],
    taxonomy_version: int,
    template_str: str,
    filters: Dict | None,
) -> Tuple[str, str, List[str]]:
    doc_ids_sorted = sorted(doc_ids)
    template_hash = hashlib.sha256(template_str.encode("utf-8")).hexdigest()
    payload = json.dumps(
        {
            "format": fmt,
            "doc_ids": doc_ids_sorted,
            "taxonomy_version": taxonomy_version,
            "template_hash": template_hash,
            "filters": filters or {},
        },
        sort_keys=True,
    )
    return (
        hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        template_hash,
        doc_ids_sorted,
    )


def _parser_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:  # pragma: no cover - git missing
        return "unknown"


def _suggestors_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:  # pragma: no cover - git missing
        return "unknown"


def _write_manifest(
    store: ObjectStore,
    export_id: str,
    doc_ids: List[str],
    taxonomy_version: int,
    template_hash: str,
    filters: Dict | None,
) -> None:
    manifest_key = export_key(export_id, "manifest.json")
    manifest = {
        "doc_ids": doc_ids,
        "taxonomy_version": taxonomy_version,
        "template_hash": template_hash,
        "filters": filters or {},
        "parser_commit": _parser_commit(),
        "suggestors_commit": _suggestors_commit(),
        "created_at": datetime.utcnow().isoformat(),
    }
    store.put_bytes(manifest_key, json.dumps(manifest, sort_keys=True).encode("utf-8"))


def export_jsonl(
    store: ObjectStore,
    *,
    doc_ids: List[str],
    template: str | None,
    preset: str | None,
    taxonomy_version: int,
    expiry: int,
    filters: Dict | None,
) -> Tuple[str, str]:
    template_str = _get_template(template, preset)
    tmpl = compile_template(template_str)
    export_id, template_hash, doc_ids_sorted = _compute_export_id(
        "jsonl", doc_ids, taxonomy_version, template_str, filters
    )
    data_key = export_key(export_id, "data.jsonl")
    manifest_key = export_key(export_id, "manifest.json")
    try:
        store.get_bytes(manifest_key)
        url = store.presign_get(data_key, expiry)
        return export_id, url
    except Exception:
        pass
    lines = [tmpl.render(chunk=ch) for ch in _load_chunks(store, doc_ids_sorted)]
    store.put_bytes(data_key, ("\n".join(lines) + "\n").encode("utf-8"))
    _write_manifest(
        store,
        export_id,
        doc_ids_sorted,
        taxonomy_version,
        template_hash,
        filters,
    )
    url = store.presign_get(data_key, expiry)
    return export_id, url


def export_csv(
    store: ObjectStore,
    *,
    doc_ids: List[str],
    template: str | None,
    preset: str | None,
    taxonomy_version: int,
    expiry: int,
    filters: Dict | None,
) -> Tuple[str, str]:
    template_str = _get_template(template, preset)
    tmpl = compile_template(template_str)
    export_id, template_hash, doc_ids_sorted = _compute_export_id(
        "csv", doc_ids, taxonomy_version, template_str, filters
    )
    data_key = export_key(export_id, "data.csv")
    manifest_key = export_key(export_id, "manifest.json")
    try:
        store.get_bytes(manifest_key)
        url = store.presign_get(data_key, expiry)
        return export_id, url
    except Exception:
        pass
    rows = [
        json.loads(tmpl.render(chunk=ch)) for ch in _load_chunks(store, doc_ids_sorted)
    ]
    headers = sorted(rows[0].keys()) if rows else []
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow({h: row.get(h, "") for h in headers})
    store.put_bytes(data_key, buf.getvalue().encode("utf-8"))
    _write_manifest(
        store,
        export_id,
        doc_ids_sorted,
        taxonomy_version,
        template_hash,
        filters,
    )
    url = store.presign_get(data_key, expiry)
    return export_id, url


__all__ = ["export_jsonl", "export_csv", "RAG_TEMPLATE"]
