from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from chunking.chunker import Block

from .html import HTMLParser
from .registry import registry


@registry.register("application/zip")
class HTMLBundleParser:
    @staticmethod
    def parse(data: bytes):
        with ZipFile(BytesIO(data)) as zf:
            for info in zf.infolist():
                if info.filename.lower().endswith(".html"):
                    file_bytes = zf.read(info)
                    for blk in HTMLParser.parse(file_bytes):
                        blk.metadata["file_path"] = info.filename
                        yield blk


__all__ = ["HTMLBundleParser"]
