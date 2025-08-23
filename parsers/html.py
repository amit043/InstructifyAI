from __future__ import annotations

from bs4 import BeautifulSoup, NavigableString, Tag  # type: ignore[import-untyped]

from chunking.chunker_v2 import Block
from core.settings import get_settings

from .html_tables import table_to_tsv
from .registry import Parser, registry


@registry.register("text/html")
class HTMLParser:
    @staticmethod
    def parse(data: bytes):
        soup = BeautifulSoup(data, "html.parser")
        for tag in soup.find_all(["nav", "footer", "aside"]):
            tag.decompose()
        stack: list[str] = []

        table_id = 0

        def traverse(node) -> "list[Block]":
            nonlocal table_id
            blocks = []
            for child in node.children:
                if isinstance(child, NavigableString):
                    text = str(child).strip()
                    if text:
                        blocks.append(Block(text=text, section_path=stack.copy()))
                elif isinstance(child, Tag):
                    name = child.name.lower()
                    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                        level = int(name[1])
                        text = child.get_text(" ", strip=True)
                        stack[:] = stack[: level - 1]
                        stack.append(text)
                        blocks.append(Block(text=text, section_path=stack.copy()))
                    elif name == "table":
                        if get_settings().tables_as_text:
                            tsv = table_to_tsv(child)
                            blocks.append(
                                Block(
                                    type="table_text",
                                    text=tsv,
                                    section_path=stack.copy(),
                                    metadata={"table_id": table_id},
                                )
                            )
                            table_id += 1
                        else:
                            blocks.append(
                                Block(
                                    type="table_placeholder",
                                    text="",
                                    section_path=stack.copy(),
                                )
                            )
                    elif name == "pre":
                        text = child.get_text("", strip=False)
                        if text:
                            blocks.append(Block(text=text, section_path=stack.copy()))
                    else:
                        blocks.extend(traverse(child))
            return blocks

        body = soup.body or soup
        for blk in traverse(body):
            yield blk


__all__ = ["HTMLParser"]
