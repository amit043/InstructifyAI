from models import JobState, JobType
from services.jobs import create_job, set_done, set_failed, set_progress
from tests.conftest import PROJECT_ID_1


def test_job_serialization(test_app) -> None:
    client, _store, _calls, SessionLocal = test_app
    with SessionLocal() as db:
        job = create_job(db, JobType.PARSE, PROJECT_ID_1, None)
        job_id = job.id
    resp = client.get(f"/jobs/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(job_id)
    assert data["type"] == JobType.PARSE.value
    assert data["state"] == JobState.QUEUED.value


def test_job_lifecycle(test_app) -> None:
    client, _store, _calls, SessionLocal = test_app
    with SessionLocal() as db:
        job = create_job(db, JobType.EXPORT, PROJECT_ID_1, None)
        set_progress(db, job.id, 40, {"foo": "bar"})
        set_done(db, job.id, {"baz": "qux"})
        db.refresh(job)
        assert job.state == JobState.SUCCEEDED
        assert job.progress == 100
        assert job.artifacts["foo"] == "bar"
        assert job.artifacts["baz"] == "qux"
        second = create_job(db, JobType.DATASET, PROJECT_ID_1, None)
        set_failed(db, second.id, "boom")
    resp = client.get("/jobs")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] >= 2
