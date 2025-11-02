import os
import uuid
from pathlib import Path
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from models import Base, Project, Document, Chunk
from models.adapter_binding import AdapterBinding
from registry.adapters import Adapter
from registry.model_registry import ModelRoute

# Ensure settings resolve to a local SQLite DB for these tests
TEST_DB = Path(__file__).with_name("test_gen_routing.sqlite")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
os.environ.setdefault("MINIO_ENDPOINT", "minio:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "test")
os.environ.setdefault("S3_BUCKET", "test-bucket")

from scripts import serve_local  # noqa: E402  (import after env patched)


class FakeModelService:
    def __init__(self, backend: str = "hf") -> None:
        self.backend_name = backend
        self.current_base_model: str | None = None
        self.current_adapter_dir: str | None = None
        self.max_new_tokens_cap = 1024
        self._queue: list[str] = []
        self.generated: list[str] = []

    def enqueue(self, *answers: str) -> None:
        self._queue.extend(answers)

    def _resolve_choice(self) -> None:  # pragma: no cover - noop for fake
        return

    def clear_backend_override(self) -> None:
        return

    def ensure_loaded(
        self,
        base_model_override: str | None = None,
        adapter_dir: str | None = None,
        backend_override: str | None = None,
    ) -> None:
        if backend_override:
            self.backend_name = backend_override
        if base_model_override:
            self.current_base_model = base_model_override
        self.current_adapter_dir = adapter_dir

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        system_prompt: str | None = None,
        stop: list[str] | None = None,
    ) -> str:
        if self._queue:
            text = self._queue.pop(0)
        else:
            text = f"fake:{prompt}"
        self.generated.append(text)
        return text


@pytest.fixture(autouse=True)
def _reset_db():
    SessionLocal = serve_local._get_db_sessionmaker()
    with SessionLocal() as session:
        engine = session.get_bind()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> TestClient:
    return TestClient(serve_local.app)


@pytest.fixture
def install_model(monkeypatch):
    def _install(texts: tuple[str, ...] = (), backend: str = "hf") -> FakeModelService:
        fake = FakeModelService(backend=backend)
        if texts:
            fake.enqueue(*texts)
        monkeypatch.setattr(serve_local, "model_svc", fake)
        return fake

    return _install


@pytest.fixture
def db_session():
    SessionLocal = serve_local._get_db_sessionmaker()
    with SessionLocal() as session:
        yield session
        session.commit()


def _create_project(session) -> Project:
    project = Project(name="Test Project", slug=f"proj-{uuid.uuid4().hex[:6]}")
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def _create_document(session, project: Project) -> Document:
    doc = Document(id=str(uuid.uuid4()), project_id=project.id, source_type="pdf")
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def _create_adapter(session, project: Project) -> Adapter:
    adapter = Adapter(
        project_id=project.id,
        name="stub-adapter",
        base_model="hf/base",
        peft_type="lora",
        task_types={},
        artifact_uri="s3://fake",
        is_active=True,
    )
    session.add(adapter)
    session.commit()
    session.refresh(adapter)
    return adapter


def test_legacy_project_only_keeps_schema(
    client: TestClient, install_model: Callable[..., FakeModelService], db_session, monkeypatch
):
    project = _create_project(db_session)
    adapter = _create_adapter(db_session, project)
    db_session.add(ModelRoute(project_id=project.id, adapter_id=adapter.id))
    db_session.commit()

    fake = install_model(("legacy answer",))
    monkeypatch.setattr(serve_local, "_download_and_unzip", lambda uri: "/tmp/adapter")
    monkeypatch.setattr(
        serve_local,
        "_resolve_adapter_targets",
        lambda adapter, path: ("hf/base", "/tmp/adapter"),
    )

    resp = client.post(
        "/gen/ask",
        json={"project_id": str(project.id), "prompt": "Say hi."},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"answer": "legacy answer"}
    assert fake.generated == ["legacy answer"]


def test_doc_specific_overrides_project(
    client: TestClient, install_model: Callable[..., FakeModelService], db_session
):
    project = _create_project(db_session)
    doc = _create_document(db_session, project)

    doc_binding = AdapterBinding(
        project_id=project.id,
        document_id=doc.id,
        backend="hf",
        base_model="hf/doc-specific",
        adapter_path="/tmp/doc-binding",
        model_ref="doc-model",
        priority=10,
    )
    project_binding = AdapterBinding(
        project_id=project.id,
        document_id=None,
        backend="hf",
        base_model="hf/project",
        adapter_path="/tmp/project-binding",
        model_ref="project-model",
        priority=20,
    )
    db_session.add_all([doc_binding, project_binding])
    db_session.commit()

    install_model(("doc binding answer",))

    resp = client.post(
        "/gen/ask",
        json={
            "project_id": str(project.id),
            "document_id": doc.id,
            "prompt": "Summarize doc binding.",
            "include_raw": True,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "doc binding answer"
    assert body["strategy"] == "first"
    assert body["raw"] == [{"model_ref": "doc-model", "text": "doc binding answer"}]
    assert body["used"] == ["doc-model"]


def test_doc_id_alias_maps_to_document_id(
    client: TestClient, install_model: Callable[..., FakeModelService], db_session
):
    project = _create_project(db_session)
    doc = _create_document(db_session, project)
    db_session.add(
        AdapterBinding(
            project_id=project.id,
            document_id=doc.id,
            backend="hf",
            base_model="hf/alias",
            adapter_path="/tmp/alias",
            model_ref="alias-model",
            priority=5,
        )
    )
    db_session.commit()

    install_model(("alias answer",))

    resp = client.post(
        "/gen/ask",
        json={
            "project_id": str(project.id),
            "doc_id": doc.id,
            "prompt": "Alias route",
            "include_raw": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "alias answer"
    assert body["used"] == ["alias-model"]
    assert body["strategy"] == "first"


def test_multi_teacher_vote(
    client: TestClient, install_model: Callable[..., FakeModelService], db_session
):
    project = _create_project(db_session)
    db_session.add_all(
        [
            AdapterBinding(
                project_id=project.id,
                document_id=None,
                backend="hf",
                base_model="hf/a",
                adapter_path="/tmp/a",
                model_ref="alpha",
                priority=5,
            ),
            AdapterBinding(
                project_id=project.id,
                document_id=None,
                backend="hf",
                base_model="hf/b",
                adapter_path="/tmp/b",
                model_ref="beta",
                priority=10,
            ),
        ]
    )
    db_session.commit()

    install_model(("Alpha wins", "Beta trails"))

    resp = client.post(
        "/gen/ask",
        json={
            "project_id": str(project.id),
            "prompt": "Vote please.",
            "strategy": "vote",
            "include_raw": True,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["strategy"] == "vote"
    assert len(body["raw"]) >= 2
    assert {entry["model_ref"] for entry in body["raw"]} == {"alpha", "beta"}


def test_model_refs_override(
    client: TestClient,
    install_model: Callable[..., FakeModelService],
    db_session,
    monkeypatch,
):
    project = _create_project(db_session)
    ref_a = AdapterBinding(
        project_id=project.id,
        document_id=None,
        backend="hf",
        base_model="hf/a",
        adapter_path="/tmp/a",
        model_ref="contracts-sft-v1",
        priority=1,
    )
    ref_b = AdapterBinding(
        project_id=project.id,
        document_id=None,
        backend="hf",
        base_model="hf/b",
        adapter_path="/tmp/b",
        model_ref="contracts-mft-v2",
        priority=2,
    )
    db_session.add_all([ref_a, ref_b])
    db_session.commit()

    install_model(("first", "second"))

    def _fail_get_bindings(*args, **kwargs):
        raise AssertionError("registry lookup should be bypassed when model_refs are provided")

    monkeypatch.setattr(serve_local, "get_bindings", _fail_get_bindings)

    resp = client.post(
        "/gen/ask",
        json={
            "project_id": str(project.id),
            "prompt": "Concat teachers.",
            "model_refs": ["contracts-sft-v1", "contracts-mft-v2"],
            "strategy": "concat",
            "include_raw": True,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "first second"
    assert body["used"] == ["contracts-sft-v1", "contracts-mft-v2"]


def test_feature_flag_off_preserves_old_behavior(
    client: TestClient,
    install_model: Callable[..., FakeModelService],
    db_session,
    monkeypatch,
):
    settings = serve_local.get_settings()
    monkeypatch.setattr(settings, "feature_doc_bindings", False)

    project = _create_project(db_session)
    doc = _create_document(db_session, project)
    adapter = _create_adapter(db_session, project)
    db_session.add(ModelRoute(project_id=project.id, adapter_id=adapter.id))
    db_session.commit()

    # Seed a binding that would have matched if the feature flag were enabled.
    db_session.add(
        AdapterBinding(
            project_id=project.id,
            document_id=doc.id,
            backend="hf",
            base_model="hf/doc",
            adapter_path="/tmp/doc",
            model_ref="doc-only",
        )
    )
    db_session.commit()

    install_model(("legacy flag off",))
    monkeypatch.setattr(serve_local, "_download_and_unzip", lambda uri: "/tmp/adapter")
    monkeypatch.setattr(
        serve_local,
        "_resolve_adapter_targets",
        lambda adapter, path: ("hf/base", "/tmp/adapter"),
    )

    resp = client.post(
        "/gen/ask",
        json={
            "project_id": str(project.id),
            "document_id": doc.id,
            "prompt": "Should ignore doc binding when feature disabled.",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {"answer": "legacy flag off"}


def test_gen_ask_returns_citations(
    client: TestClient,
    install_model: Callable[..., FakeModelService],
    db_session,
    monkeypatch,
):
    project = _create_project(db_session)
    doc = _create_document(db_session, project)
    adapter = _create_adapter(db_session, project)
    db_session.add(ModelRoute(project_id=project.id, adapter_id=adapter.id))

    chunk_id = str(uuid.uuid4())
    chunk = Chunk(
        id=chunk_id,
        document_id=doc.id,
        version=1,
        order=1,
        content={"text": "Policy section 1.2: Always cite the rule.", "section_path": ["Policy", "1.2"]},
        text_hash="hash1",
        meta={},
    )
    db_session.add(chunk)
    db_session.commit()

    install_model((f"Follow the rule from [{chunk_id}].",))
    monkeypatch.setattr(serve_local, "_download_and_unzip", lambda uri: "/tmp/adapter")
    monkeypatch.setattr(
        serve_local,
        "_resolve_adapter_targets",
        lambda adapter, path: ("hf/base", "/tmp/adapter"),
    )

    resp = client.post(
        "/gen/ask",
        json={
            "project_id": str(project.id),
            "document_id": doc.id,
            "prompt": "What does the policy say?",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == f"Follow the rule from [{chunk_id}]."
    assert "citations" in body
    assert body.get("needs_grounding") in (None, False)
    citation_ids = {entry["chunk_id"] for entry in body["citations"]}
    assert chunk_id in citation_ids


def test_gen_ask_fallback_when_missing_citation(
    client: TestClient,
    install_model: Callable[..., FakeModelService],
    db_session,
    monkeypatch,
):
    project = _create_project(db_session)
    doc = _create_document(db_session, project)
    adapter = _create_adapter(db_session, project)
    db_session.add(ModelRoute(project_id=project.id, adapter_id=adapter.id))

    chunk_id = str(uuid.uuid4())
    chunk = Chunk(
        id=chunk_id,
        document_id=doc.id,
        version=1,
        order=1,
        content={"text": "Reference section 5 for escalation steps.", "section_path": ["Playbook", "Escalation"]},
        text_hash="hash2",
        meta={},
    )
    db_session.add(chunk)
    db_session.commit()

    fake = install_model(("Uncited answer", "Still no cite"))
    fallback_text = "No grounded answer available."

    settings = serve_local.get_settings()
    monkeypatch.setattr(settings, "gen_fallback_answer", fallback_text)
    monkeypatch.setattr(settings, "gen_retry_on_missing_citations", True)

    monkeypatch.setattr(serve_local, "_download_and_unzip", lambda uri: "/tmp/adapter")
    monkeypatch.setattr(
        serve_local,
        "_resolve_adapter_targets",
        lambda adapter, path: ("hf/base", "/tmp/adapter"),
    )

    resp = client.post(
        "/gen/ask",
        json={
            "project_id": str(project.id),
            "document_id": doc.id,
            "prompt": "How do I escalate an incident?",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == fallback_text
    assert body["needs_grounding"] is True
    assert body.get("original_answer") == "Still no cite"
    assert body["fallback_reason"] in {"missing_citation", "no_evidence"}
    if body["fallback_reason"] == "missing_citation":
        assert any(entry["chunk_id"] == chunk_id for entry in body.get("citations", []))
    else:
        assert body.get("citations", []) == []


def test_gen_ask_filters_low_rank_evidence(
    client: TestClient,
    install_model: Callable[..., FakeModelService],
    db_session,
    monkeypatch,
):
    project = _create_project(db_session)
    doc = _create_document(db_session, project)
    adapter = _create_adapter(db_session, project)
    db_session.add(ModelRoute(project_id=project.id, adapter_id=adapter.id))

    chunk_id = str(uuid.uuid4())
    chunk = Chunk(
        id=chunk_id,
        document_id=doc.id,
        version=1,
        order=1,
        content={"text": "Irrelevant text", "section_path": ["Noise"]},
        text_hash="hash-low",
        meta={},
    )
    db_session.add(chunk)
    db_session.commit()

    fake = install_model(("Low rank answer",))

    settings = serve_local.get_settings()
    monkeypatch.setattr(settings, "gen_min_rank_score", 0.9)
    monkeypatch.setattr(settings, "gen_retry_on_missing_citations", False)
    monkeypatch.setattr(settings, "gen_fallback_answer", "No grounded answer available.")

    def _fake_retrieve(*args, **kwargs):
        return [
            {
                "chunk_id": chunk_id,
                "doc_id": doc.id,
                "order": 1,
                "text": "Irrelevant text",
                "section_path": ["Noise"],
                "score": 0.05,
                "rank_score": 0.05,
                "text_hash": "hash-low",
            }
        ]

    monkeypatch.setattr(serve_local, "retrieve_evidence", _fake_retrieve)
    monkeypatch.setattr(serve_local, "_download_and_unzip", lambda uri: "/tmp/adapter")
    monkeypatch.setattr(
        serve_local,
        "_resolve_adapter_targets",
        lambda adapter, path: ("hf/base", "/tmp/adapter"),
    )

    resp = client.post(
        "/gen/ask",
        json={
            "project_id": str(project.id),
            "document_id": doc.id,
            "prompt": "What is apple?",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == settings.gen_fallback_answer
    assert body["needs_grounding"] is True
    assert body["fallback_reason"] == "no_evidence"
    assert body.get("citations", []) == []
    assert fake.generated
