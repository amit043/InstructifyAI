from __future__ import annotations

import unicodedata

from sqlalchemy.orm import Session

from models import DocumentVersion


def normalize(
    db: Session,
    doc_version: DocumentVersion,
    data: bytes,
    encoding: str,
) -> str:
    text = data.decode(encoding, errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFKC", text)
    cleaned: list[str] = []
    control_count = 0
    for ch in text:
        if unicodedata.category(ch) == "Cc" and ch not in "\n\t":
            control_count += 1
            continue
        cleaned.append(ch)
    result = "".join(cleaned)
    meta = dict(doc_version.meta)
    parse_meta = dict(meta.get("parse", {}))
    parse_meta.update({"control_char_count": control_count})
    meta["parse"] = parse_meta
    doc_version.meta = meta
    db.add(doc_version)
    db.commit()
    return result


__all__ = ["normalize"]
