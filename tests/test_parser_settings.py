from sqlalchemy import select

from models import DocumentVersion
from tests.conftest import PROJECT_ID_1
from worker import main as worker_main


def _setup_worker(store, SessionLocal):
    worker_main.create_client = lambda **kwargs: store.client
    worker_main.settings.s3_bucket = store.bucket
    worker_main.SessionLocal = SessionLocal


def test_parser_settings_toggle(test_app) -> None:
    client, store, calls, SessionLocal = test_app
    resp = client.patch(
        f"/projects/{PROJECT_ID_1}/settings",
        json={
            "ocr_langs": ["eng", "deu"],
            "min_text_len_for_ocr": 10,
            "html_crawl_limits": {"max_depth": 3, "max_pages": 5},
        },
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    resp = client.get(f"/projects/{PROJECT_ID_1}/settings")
    assert resp.json()["ocr_langs"] == ["eng", "deu"]
    assert resp.json()["min_text_len_for_ocr"] == 10
    assert resp.json()["html_crawl_limits"] == {"max_depth": 3, "max_pages": 5}

    html = "<html><body><p>Hello</p></body></html>"
    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("test.html", html, "text/html")},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["doc_id"]

    _setup_worker(store, SessionLocal)
    worker_main.parse_document(doc_id, 1)

    with SessionLocal() as db:
        ver = db.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == doc_id)
        )
        assert ver is not None
        settings_meta = ver.meta.get("parser_settings")
        assert settings_meta["ocr_langs"] == ["eng", "deu"]
        assert settings_meta["min_text_len_for_ocr"] == 10
        assert settings_meta["html_crawl_limits"] == {"max_depth": 3, "max_pages": 5}
