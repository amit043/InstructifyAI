from __future__ import annotations

import json

from storage.object_store import raw_key

from .html import HTMLParser
from .registry import registry


@registry.register("application/x-crawl")  # type: ignore[arg-type]
class HTMLCrawlParser:
    @staticmethod
    def parse(data: bytes, *, store, doc_id: str):
        index = json.loads(data.decode("utf-8"))
        for url, filename in index.items():
            page_bytes = store.get_bytes(raw_key(doc_id, f"crawl/{filename}"))
            for blk in HTMLParser.parse(page_bytes):
                blk.metadata["file_path"] = filename
                blk.metadata["url"] = url
                yield blk


__all__ = ["HTMLCrawlParser"]
