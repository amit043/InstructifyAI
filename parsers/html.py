from __future__ import annotations

from bs4 import BeautifulSoup, NavigableString, Tag  # type: ignore[import-untyped]

from chunking.chunker import Block

from .registry import registry


@registry.register("html")
def parse_html(data: bytes):
    soup = BeautifulSoup(data, "html.parser")
    for tag in soup.find_all(["nav", "footer", "aside"]):
        tag.decompose()
    stack: list[str] = []

    def traverse(node) -> "list[Block]":
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
                    blocks.append(
                        Block(
                            type="table_placeholder", text="", section_path=stack.copy()
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
