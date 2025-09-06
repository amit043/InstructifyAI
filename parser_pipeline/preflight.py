from __future__ import annotations

import mimetypes
from dataclasses import dataclass

from charset_normalizer import from_bytes
from sqlalchemy.orm import Session

from models import DocumentVersion


@dataclass
class PreflightResult:
    mime: str
    encoding: str
    non_utf8_ratio: float


def _detect_mime(filename: str | None, head: bytes) -> str:
    if head.startswith(b"%PDF"):
        return "application/pdf"
    if b"<html" in head.lower() or head.lstrip().startswith(b"<!DOCTYPE html"):
        return "text/html"
    if filename:
        guess, _ = mimetypes.guess_type(filename)
        if guess:
            return guess
    return "application/octet-stream"


def preflight(
    db: Session,
    doc_version: DocumentVersion,
    data: bytes,
    filename: str | None = None,
) -> PreflightResult:
    head = data[:4096]
    mime = _detect_mime(filename, head)
    best = from_bytes(head).best()
    encoding = best.encoding if best and best.encoding else "utf-8"
    try:
        data.decode("utf-8")
        non_utf8_ratio = 0.0
    except UnicodeDecodeError:
        decoded = data.decode("utf-8", errors="ignore")
        non_utf8_ratio = (len(data) - len(decoded.encode("utf-8"))) / len(data)
    meta = dict(doc_version.meta)
    parse_meta = dict(meta.get("parse", {}))
    parse_meta.update({"non_utf8_ratio": non_utf8_ratio})
    meta["parse"] = parse_meta
    doc_version.meta = meta
    db.add(doc_version)
    db.commit()
    return PreflightResult(mime=mime, encoding=encoding, non_utf8_ratio=non_utf8_ratio)


__all__ = ["PreflightResult", "preflight"]
