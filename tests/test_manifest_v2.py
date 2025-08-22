import json
import uuid

from chunking.chunker import Chunk, ChunkContent, ChunkSource
from storage.object_store import derived_key
from worker.derived_writer import upsert_chunks


def test_manifest_v2_fields_and_presign(test_app):
    _, store, _, SessionLocal = test_app
    with SessionLocal() as db:
        doc_id = str(uuid.uuid4())
        chunks = [
            Chunk(
                id=uuid.uuid4(),
                order=0,
                content=ChunkContent(type="text", text="alpha"),
                source=ChunkSource(page=1, section_path=[]),
                text_hash="h1",
                metadata={"file_path": "a.html"},
            ),
            Chunk(
                id=uuid.uuid4(),
                order=1,
                content=ChunkContent(type="text", text="beta"),
                source=ChunkSource(page=2, section_path=[]),
                text_hash="h2",
                metadata={"source_stage": "pdf_ocr"},
            ),
        ]
        metrics = {"empty_chunk_ratio": 0.5}
        chunks_url, manifest_url = upsert_chunks(
            db,
            store,
            doc_id=doc_id,
            version=1,
            chunks=chunks,
            metrics=metrics,
        )
    manifest_key = derived_key(doc_id, "manifest.json")
    manifest = json.loads(store.client.store[manifest_key])
    assert manifest["tool_versions"]["pymupdf"]
    assert "tesseract" in manifest["tool_versions"]
    assert manifest["thresholds"]["empty_chunk_ratio"] > 0
    assert manifest["stage_metrics"]["empty_chunk_ratio"] == 0.5
    assert manifest["files"] == ["a.html"]
    assert manifest["pages_ocr"] == [2]
    assert manifest["langs_used"] == []
    assert manifest["page_langs"] == []
    assert "created_at" in manifest
    assert "X-Amz-Expires" in chunks_url
    assert "X-Amz-Expires" in manifest_url
