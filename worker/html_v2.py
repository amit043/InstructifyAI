from __future__ import annotations

from typing import Tuple

from sqlalchemy.orm import Session

from models import Document, DocumentVersion
from storage.object_store import ObjectStore
from worker.v1 import run_parse_v1


def parse_html_v2(
    db: Session,
    store: ObjectStore,
    doc: Document,
    dv: DocumentVersion,
    *,
    settings: dict | None = None,
    parser_overrides: dict | None = None,
    job_id: str | None = None,
) -> Tuple[list[dict], dict, dict, dict[str, list[dict[str, str]]]]:
    """
    V2 HTML parser stub. Currently delegates to V1 behavior.
    TODO: implement structure/boilerplate improvements in a future iteration.
    """
    _ = settings, job_id
    return run_parse_v1(db, store, doc, dv, parser_overrides or {}, [], False)


__all__ = ["parse_html_v2"]
