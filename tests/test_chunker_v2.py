from chunking.chunker_v2 import Block, chunk_blocks


def _text(words: int) -> str:
    return "word " * words


def test_chunker_v2_boundaries_and_meta() -> None:
    blocks = [
        Block(text="intro", file_path="a.txt", page=1, section_path=["Intro"]),
        Block(
            text="Section A",
            file_path="a.txt",
            page=1,
            section_path=["Section A"],
            metadata={"kind": "title"},
        ),
        Block(
            text="content one",
            file_path="a.txt",
            page=1,
            section_path=["Section A"],
        ),
        Block(text="other", file_path="b.txt", page=2, section_path=["Other"]),
    ]
    chunks = chunk_blocks(blocks, max_tokens=50)
    assert len(chunks) == 3
    assert chunks[0].content.text == "intro"
    assert chunks[1].content.text is not None
    assert chunks[1].content.text.startswith("Section A\ncontent one")
    assert chunks[2].metadata["file_path"] == "b.txt"
    assert chunks[1].metadata == {
        "file_path": "a.txt",
        "page": 1,
        "section_path": ["Section A"],
    }


def test_chunker_v2_deterministic() -> None:
    blocks = [
        Block(text=_text(10), file_path="a", page=1, section_path=["A"]),
        Block(text=_text(10), file_path="a", page=1, section_path=["A"]),
        Block(text=_text(10), file_path="b", page=1, section_path=["B"]),
    ]
    chunks1 = chunk_blocks(blocks, max_tokens=15)
    chunks2 = chunk_blocks(blocks, max_tokens=15)
    assert chunks1 == chunks2
