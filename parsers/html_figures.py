from __future__ import annotations

from dataclasses import dataclass
from typing import List

from bs4 import BeautifulSoup, Tag


@dataclass
class HTMLFigure:
    src: str
    caption: str | None


def extract_figures(html: str) -> List[HTMLFigure]:
    """Return figures with image source and caption text.

    Only <figure> tags containing an <img> are considered. The caption is taken
    from a nested <figcaption> if present.
    """
    soup = BeautifulSoup(html, "html.parser")
    figures: List[HTMLFigure] = []
    for fig in soup.find_all("figure"):
        if not isinstance(fig, Tag):
            continue
        img = fig.find("img")
        if not isinstance(img, Tag):
            continue
        src = str(img.get("src") or "")
        caption_tag = fig.find("figcaption")
        caption = (
            caption_tag.get_text(" ", strip=True)
            if isinstance(caption_tag, Tag)
            else None
        )
        figures.append(HTMLFigure(src=src, caption=caption))
    return figures


__all__ = ["HTMLFigure", "extract_figures"]
