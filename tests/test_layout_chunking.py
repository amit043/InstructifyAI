from chunking.chunker_v2 import Block, chunk_blocks
from exporters.common import ExportChunk
from parser_pipeline.structure import structure


def test_structure_html_list_detects_steps() -> None:
    html = "<h1>Proc</h1><ol><li>First</li><li>Second</li></ol>"
    blocks = list(structure(html.encode("utf-8"), source_type="text/html"))
    kinds = [b.metadata.get("kind") for b in blocks]
    assert kinds == ["title", "step", "step"]


def test_chunker_step_ids_and_sections() -> None:
    blocks = [
        Block(text="Intro", file_path="a", page=1, section_path=["Proc"]),
        Block(
            text="Step 1: Do X",
            file_path="a",
            page=1,
            section_path=["Proc"],
            metadata={"kind": "step"},
        ),
        Block(
            text="More details",
            file_path="a",
            page=1,
            section_path=["Proc"],
        ),
        Block(
            text="Step 2: Do Y",
            file_path="a",
            page=1,
            section_path=["Proc"],
            metadata={"kind": "step"},
        ),
    ]
    chunks = chunk_blocks(blocks, max_tokens=50)
    assert [c.metadata.get("step_id") for c in chunks] == [None, 1, 2]
    assert chunks[1].metadata["section_path"] == ["Proc"]
    ec = ExportChunk(
        doc_id="d",
        chunk_id=str(chunks[1].id),
        order=chunks[1].order,
        content={"type": chunks[1].content.type, "text": chunks[1].content.text},
        source={
            "page": chunks[1].metadata.get("page"),
            "section_path": chunks[1].metadata["section_path"],
        },
        text_hash=chunks[1].text_hash,
        metadata=chunks[1].metadata,
    )
    assert ec.step_id == 1
