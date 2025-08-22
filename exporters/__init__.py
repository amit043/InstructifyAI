import csv
import hashlib
import io
import json
import subprocess
from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple

from core.dedupe import drop_near_duplicates
from storage.object_store import ObjectStore, derived_key, export_key, signed_url

from .hf_bundle import pack_datasetdict
from .parquet_writer import write_parquet
from .presets import RAG_TEMPLATE, SFT_TEMPLATE, get_preset
from .templates import compile_template


def _get_template(template: str | None, preset: str | None) -> str:
    if preset:
        return get_preset(preset)
    if template is None:
        raise ValueError("template or preset required")
    return template


def _load_redactions(store: ObjectStore, doc_id: str) -> Dict[str, List[dict]]:
    try:
        data = (
            store.get_bytes(derived_key(doc_id, "redactions.jsonl"))
            .decode("utf-8")
            .strip()
        )
    except Exception:
        return {}
    result: Dict[str, List[dict]] = {}
    if data:
        for line in data.splitlines():
            item = json.loads(line)
            result[item["chunk_id"]] = item.get("redactions", [])
    return result


def _load_chunks(
    store: ObjectStore,
    doc_ids: List[str],
    project: Any | None = None,
    *,
    exclude_pii: bool = True,
) -> Iterable[dict]:
    counts: Dict[str, int] = {doc_id: 0 for doc_id in doc_ids}
    red_map: Dict[str, Dict[str, List[dict]]] = {}
    if exclude_pii:
        for doc_id in doc_ids:
            red_map[doc_id] = _load_redactions(store, doc_id)
    for doc_id in doc_ids:
        data = (
            store.get_bytes(derived_key(doc_id, "chunks.jsonl")).decode("utf-8").strip()
        )
        if not data:
            continue
        for line in data.splitlines():
            ch = json.loads(line)
            if exclude_pii and ch["content"].get("text"):
                reds = red_map.get(doc_id, {}).get(ch["chunk_id"], [])
                if reds:
                    for r in reds:
                        ch["content"]["text"] = ch["content"]["text"].replace(
                            r["text"], "[REDACTED]"
                        )
                    meta = ch.get("metadata", {})
                    if meta.get("suggestions"):
                        meta["suggestions"].pop("redactions", None)
            if project:
                meta = ch.get("metadata", {})
                sugg = meta.get("suggestions")
                if sugg:
                    if not (project.use_rules_suggestor or project.use_mini_llm):
                        meta.pop("suggestions", None)
                    else:
                        remaining = project.max_suggestions_per_doc - counts[doc_id]
                        if remaining <= 0:
                            meta.pop("suggestions", None)
                        else:
                            if len(sugg) > remaining:
                                keys = list(sugg.keys())[:remaining]
                                meta["suggestions"] = {k: sugg[k] for k in keys}
                                counts[doc_id] += len(keys)
                            else:
                                counts[doc_id] += len(sugg)
            yield ch


def _compute_export_id(
    fmt: str,
    doc_ids: List[str],
    taxonomy_version: int,
    template_str: str,
    filters: Dict | None,
    project: Any | None,
    drop_near_dupes: bool,
    dupe_threshold: float,
    exclude_pii: bool,
) -> Tuple[str, str, List[str]]:
    doc_ids_sorted = sorted(doc_ids)
    template_hash = hashlib.sha256(template_str.encode("utf-8")).hexdigest()
    payload_dict: Dict[str, Any] = {
        "format": fmt,
        "doc_ids": doc_ids_sorted,
        "taxonomy_version": taxonomy_version,
        "template_hash": template_hash,
        "filters": filters or {},
        "drop_near_dupes": drop_near_dupes,
        "dupe_threshold": dupe_threshold,
        "exclude_pii": exclude_pii,
    }
    if project:
        payload_dict["project_settings"] = {
            "use_rules_suggestor": project.use_rules_suggestor,
            "use_mini_llm": project.use_mini_llm,
            "max_suggestions_per_doc": project.max_suggestions_per_doc,
            "suggestion_timeout_ms": project.suggestion_timeout_ms,
        }
    payload = json.dumps(payload_dict, sort_keys=True)
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
    project: Any | None,
    drop_stats: Dict | None,
) -> None:
    manifest_key = export_key(export_id, "manifest.json")
    manifest = {
        "doc_ids": doc_ids,
        "taxonomy_version": taxonomy_version,
        "template_hash": template_hash,
        "filters": filters or {},
        "parser_commit": _parser_commit(),
        "suggestors_commit": _suggestors_commit(),
        "project_settings": (
            {
                "use_rules_suggestor": project.use_rules_suggestor,
                "use_mini_llm": project.use_mini_llm,
                "max_suggestions_per_doc": project.max_suggestions_per_doc,
                "suggestion_timeout_ms": project.suggestion_timeout_ms,
            }
            if project
            else {}
        ),
        "created_at": datetime.utcnow().isoformat(),
    }
    if drop_stats:
        manifest["drop_stats"] = drop_stats
    store.put_bytes(manifest_key, json.dumps(manifest, sort_keys=True).encode("utf-8"))


def export_jsonl(
    store: ObjectStore,
    *,
    doc_ids: List[str],
    template: str | None,
    preset: str | None,
    taxonomy_version: int,
    filters: Dict | None,
    project: Any | None = None,
    drop_near_dupes: bool = False,
    dupe_threshold: float = 0.85,
    exclude_pii: bool = True,
) -> Tuple[str, str]:
    template_str = _get_template(template, preset)
    tmpl = compile_template(template_str)
    export_id, template_hash, doc_ids_sorted = _compute_export_id(
        "jsonl",
        doc_ids,
        taxonomy_version,
        template_str,
        filters,
        project,
        drop_near_dupes,
        dupe_threshold,
        exclude_pii,
    )
    data_key = export_key(export_id, "data.jsonl")
    manifest_key = export_key(export_id, "manifest.json")
    try:
        store.get_bytes(manifest_key)
        url = signed_url(store, data_key)
        return export_id, url
    except Exception:
        pass
    chunks = list(_load_chunks(store, doc_ids_sorted, project, exclude_pii=exclude_pii))
    drop_stats = None
    if drop_near_dupes:
        chunks, stats = drop_near_duplicates(chunks, dupe_threshold)
        drop_stats = {"near_duplicates": stats}
    lines = [tmpl.render(chunk=ch) for ch in chunks]
    store.put_bytes(data_key, ("\n".join(lines) + "\n").encode("utf-8"))
    _write_manifest(
        store,
        export_id,
        doc_ids_sorted,
        taxonomy_version,
        template_hash,
        filters,
        project,
        drop_stats,
    )
    url = signed_url(store, data_key)
    return export_id, url


def export_csv(
    store: ObjectStore,
    *,
    doc_ids: List[str],
    template: str | None,
    preset: str | None,
    taxonomy_version: int,
    filters: Dict | None,
    project: Any | None = None,
    drop_near_dupes: bool = False,
    dupe_threshold: float = 0.85,
    exclude_pii: bool = True,
) -> Tuple[str, str]:
    template_str = _get_template(template, preset)
    tmpl = compile_template(template_str)
    export_id, template_hash, doc_ids_sorted = _compute_export_id(
        "csv",
        doc_ids,
        taxonomy_version,
        template_str,
        filters,
        project,
        drop_near_dupes,
        dupe_threshold,
        exclude_pii,
    )
    data_key = export_key(export_id, "data.csv")
    manifest_key = export_key(export_id, "manifest.json")
    try:
        store.get_bytes(manifest_key)
        url = signed_url(store, data_key)
        return export_id, url
    except Exception:
        pass
    chunks = list(_load_chunks(store, doc_ids_sorted, project, exclude_pii=exclude_pii))
    drop_stats = None
    if drop_near_dupes:
        chunks, stats = drop_near_duplicates(chunks, dupe_threshold)
        drop_stats = {"near_duplicates": stats}
    rows = [json.loads(tmpl.render(chunk=ch)) for ch in chunks]
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
        project,
        drop_stats,
    )
    url = signed_url(store, data_key)
    return export_id, url


def export_parquet(
    store: ObjectStore,
    *,
    doc_ids: List[str],
    template: str | None,
    preset: str | None,
    taxonomy_version: int,
    filters: Dict | None,
    project: Any | None = None,
    drop_near_dupes: bool = False,
    dupe_threshold: float = 0.85,
    exclude_pii: bool = True,
) -> Tuple[str, str]:
    template_str = _get_template(template, preset)
    tmpl = compile_template(template_str)
    export_id, template_hash, doc_ids_sorted = _compute_export_id(
        "parquet",
        doc_ids,
        taxonomy_version,
        template_str,
        filters,
        project,
        drop_near_dupes,
        dupe_threshold,
        exclude_pii,
    )
    data_key = export_key(export_id, "data.parquet")
    manifest_key = export_key(export_id, "manifest.json")
    try:
        store.get_bytes(manifest_key)
        url = signed_url(store, data_key)
        return export_id, url
    except Exception:
        pass
    chunks = list(_load_chunks(store, doc_ids_sorted, project, exclude_pii=exclude_pii))
    drop_stats = None
    if drop_near_dupes:
        chunks, stats = drop_near_duplicates(chunks, dupe_threshold)
        drop_stats = {"near_duplicates": stats}
    rows = [json.loads(tmpl.render(chunk=ch)) for ch in chunks]
    buf = write_parquet(rows)
    store.put_bytes(data_key, buf)
    _write_manifest(
        store,
        export_id,
        doc_ids_sorted,
        taxonomy_version,
        template_hash,
        filters,
        project,
        drop_stats,
    )
    url = signed_url(store, data_key)
    return export_id, url


def export_hf(
    store: ObjectStore,
    *,
    doc_ids: List[str],
    template: str | None,
    preset: str | None,
    taxonomy_version: int,
    filters: Dict | None,
    project: Any | None = None,
    drop_near_dupes: bool = False,
    dupe_threshold: float = 0.85,
    exclude_pii: bool = True,
) -> Tuple[str, str]:
    template_str = _get_template(template, preset)
    tmpl = compile_template(template_str)
    export_id, template_hash, doc_ids_sorted = _compute_export_id(
        "hf",
        doc_ids,
        taxonomy_version,
        template_str,
        filters,
        project,
        drop_near_dupes,
        dupe_threshold,
        exclude_pii,
    )
    data_key = export_key(export_id, "data.hf")
    manifest_key = export_key(export_id, "manifest.json")
    try:
        store.get_bytes(manifest_key)
        url = signed_url(store, data_key)
        return export_id, url
    except Exception:
        pass
    chunks = list(_load_chunks(store, doc_ids_sorted, project, exclude_pii=exclude_pii))
    drop_stats = None
    if drop_near_dupes:
        chunks, stats = drop_near_duplicates(chunks, dupe_threshold)
        drop_stats = {"near_duplicates": stats}
    rows = [json.loads(tmpl.render(chunk=ch)) for ch in chunks]
    buf = pack_datasetdict(rows)
    store.put_bytes(data_key, buf)
    _write_manifest(
        store,
        export_id,
        doc_ids_sorted,
        taxonomy_version,
        template_hash,
        filters,
        project,
        drop_stats,
    )
    url = signed_url(store, data_key)
    return export_id, url


__all__ = [
    "export_jsonl",
    "export_csv",
    "export_parquet",
    "export_hf",
    "RAG_TEMPLATE",
    "SFT_TEMPLATE",
]
