import uuid
from types import SimpleNamespace

import pytest

from models.dataset import Dataset
from registry.adapters import TrainingRun
from models.document import Document
from tests.conftest import PROJECT_ID_1


@pytest.fixture
def mock_training_task(monkeypatch):
    payload: dict = {}

    def capture(run_id, config):
        payload["run_id"] = run_id
        payload["config"] = config

    monkeypatch.setattr(
        "api.routes.training.run_training_task",
        SimpleNamespace(delay=capture),
    )
    return payload


@pytest.fixture
def fixed_knobs(monkeypatch):
    knobs = {
        "peft": "lora",
        "quant": "fp16",
        "batch_size": 1,
        "grad_accum": 4,
        "max_seq_len": 1024,
    }

    def _select(base_model: str, prefer_small: bool):
        return knobs.copy()

    monkeypatch.setattr("api.routes.training.select_training_knobs", _select)
    return knobs


def _seed_dataset(session) -> Dataset:
    dataset_id = uuid.uuid4()
    snapshot_uri = f"s3://bucket/{dataset_id}/snapshot.jsonl"
    dataset = Dataset(
        id=dataset_id,
        project_id=PROJECT_ID_1,
        name="demo",
        filters={},
        snapshot_uri=snapshot_uri,
        stats={},
    )
    session.add(dataset)
    session.commit()
    return dataset


def _seed_dataset_and_run(
    session, document_id: uuid.UUID | None = None, create_document: bool = True
):
    dataset = _seed_dataset(session)
    if document_id and create_document:
        session.add(
            Document(
                id=str(document_id),
                project_id=PROJECT_ID_1,
                source_type="pdf",
            )
        )
    run = TrainingRun(
        id=uuid.uuid4(),
        project_id=PROJECT_ID_1,
        mode="sft",
        base_model="orig/base",
        peft_type="lora",
        input_uri=dataset.snapshot_uri,
        output_uri="s3://old/artifact.zip",
        document_id=document_id,
        status="failed",
        metrics={"train_loss": 1.2},
    )
    session.add(run)
    session.commit()
    return dataset, run


def test_resume_training_run_enqueue(test_app, mock_training_task, fixed_knobs):
    client, _, _, SessionLocal = test_app
    with SessionLocal() as session:
        dataset, run = _seed_dataset_and_run(session)

    resp = client.post(
        f"/training/runs/{run.id}/resume",
        json={"epochs": 3, "lr": 0.0002},
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(run.id)
    assert mock_training_task["run_id"] == str(run.id)
    config = mock_training_task["config"]
    assert config["dataset_snapshot_uri"] == dataset.snapshot_uri
    assert config["epochs"] == 3
    assert config["project_id"] == str(PROJECT_ID_1)
    assert config["knobs"]["peft"] == "lora"

    with SessionLocal() as session:
        refreshed = session.get(TrainingRun, run.id)
        assert refreshed is not None
        assert refreshed.status == "queued"
        assert refreshed.output_uri == ""
        assert refreshed.metrics is None


def test_resume_training_run_conflict(test_app, fixed_knobs, mock_training_task):
    client, _, _, SessionLocal = test_app
    with SessionLocal() as session:
        dataset, run = _seed_dataset_and_run(session)
        run.status = "running"
        session.commit()

    resp = client.post(
        f"/training/runs/{run.id}/resume",
        json={},
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"].startswith("run already in progress")
    assert mock_training_task == {}



def test_resume_training_run_force(test_app, fixed_knobs, mock_training_task):
    client, _, _, SessionLocal = test_app
    with SessionLocal() as session:
        dataset, run = _seed_dataset_and_run(session)
        run.status = "running"
        session.commit()

    resp = client.post(
        f"/training/runs/{run.id}/resume",
        json={"force": True, "epochs": 5},
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    assert mock_training_task["run_id"] == str(run.id)
    config = mock_training_task["config"]
    assert config["epochs"] == 5
    assert config["dataset_snapshot_uri"] == dataset.snapshot_uri

    with SessionLocal() as session:
        refreshed = session.get(TrainingRun, run.id)
        assert refreshed is not None
        assert refreshed.status == "queued"

def test_resume_training_run_with_document_id(test_app, fixed_knobs, mock_training_task):
    client, _, _, SessionLocal = test_app
    doc_id = uuid.uuid4()
    with SessionLocal() as session:
        dataset, run = _seed_dataset_and_run(session, document_id=doc_id)

    resp = client.post(
        f"/training/runs/{run.id}/resume",
        json={"force": True},
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == str(doc_id)
    config = mock_training_task["config"]
    assert config["document_id"] == str(doc_id)
    assert config["dataset_snapshot_uri"] == dataset.snapshot_uri




def test_create_training_run_with_document(test_app, mock_training_task, fixed_knobs):
    client, _, _, SessionLocal = test_app
    doc_id = uuid.uuid4()
    with SessionLocal() as session:
        dataset = _seed_dataset(session)
        session.add(
            Document(
                id=str(doc_id),
                project_id=PROJECT_ID_1,
                source_type="pdf",
            )
        )
        session.commit()

    payload = {
        "project_id": str(PROJECT_ID_1),
        "dataset_id": str(dataset.id),
        "mode": "sft",
        "epochs": 1,
        "document_id": str(doc_id),
    }
    resp = client.post(
        "/training/runs",
        json=payload,
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == str(doc_id)
    config = mock_training_task["config"]
    assert config["document_id"] == str(doc_id)


def test_create_training_run_invalid_document(test_app, mock_training_task, fixed_knobs):
    client, _, _, SessionLocal = test_app
    with SessionLocal() as session:
        dataset = _seed_dataset(session)
    payload = {
        "project_id": str(PROJECT_ID_1),
        "dataset_id": str(dataset.id),
        "mode": "sft",
        "epochs": 1,
        "document_id": str(uuid.uuid4()),
    }
    resp = client.post(
        "/training/runs",
        json=payload,
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 404
    assert "document" in resp.json()["detail"]
    assert mock_training_task == {}


def test_resume_training_run_missing_document(test_app, fixed_knobs, mock_training_task):
    client, _, _, SessionLocal = test_app
    missing_doc_id = uuid.uuid4()
    with SessionLocal() as session:
        dataset, run = _seed_dataset_and_run(
            session, document_id=missing_doc_id, create_document=False
        )

    resp = client.post(
        f"/training/runs/{run.id}/resume",
        json={"force": True},
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 404
    assert "document" in resp.json()["detail"]
    assert mock_training_task == {}
