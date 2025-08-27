import uuid

from api.main import app, get_label_studio_client
from models import Chunk, Document, Taxonomy
from tests.conftest import PROJECT_ID_1


class FakeLSClient:
    def __init__(self) -> None:
        self.base_url = "http://ls"
        self.tasks: list[dict] = []
        self.webhook_url: str | None = None

    def upsert_project(self, slug: str, title: str | None = None) -> dict:
        return {"id": 1}

    def set_project_config(self, project_id: int, config: str) -> None:
        pass

    def create_tasks(self, project_id: int, tasks, batch_size: int = 100) -> int:
        self.tasks.extend(tasks)
        return len(tasks)

    def ensure_webhook(self, project_id: int, url: str) -> None:
        self.webhook_url = url

    def check_connection(self) -> bool:
        return True

    def has_webhook(self, url: str) -> bool:
        return self.webhook_url == url


def test_sync_endpoint(test_app):
    client, _, _, SessionLocal = test_app
    fake = FakeLSClient()
    app.dependency_overrides[get_label_studio_client] = lambda: fake
    with SessionLocal() as db:
        doc_id = str(uuid.uuid4())
        db.add(Document(id=doc_id, project_id=PROJECT_ID_1, source_type="pdf"))
        db.add(
            Chunk(
                id="c1",
                document_id=doc_id,
                version=1,
                order=1,
                content={"type": "text", "text": "hello"},
                text_hash="h1",
                meta={},
            )
        )
        db.add(Taxonomy(project_id=PROJECT_ID_1, version=1, fields=[]))
        db.commit()
    r = client.post(
        f"/integrations/label-studio/projects/{PROJECT_ID_1}/sync",
        json={"doc_ids": [doc_id], "dataset": "chunks", "limit": 200},
        headers={"X-Role": "curator"},
    )
    assert r.status_code == 200
    assert r.json()["pushed"] == 1
    assert fake.tasks and fake.tasks[0]["id"] == "c1"


def test_health_endpoint(test_app):
    client, _, _, _ = test_app
    fake = FakeLSClient()
    fake.webhook_url = "http://testserver/webhooks/label-studio"
    app.dependency_overrides[get_label_studio_client] = lambda: fake
    r = client.get("/integrations/label-studio/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "webhook": True}
