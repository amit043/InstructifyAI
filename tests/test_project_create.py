import uuid

from models import Project


def test_create_project(test_app) -> None:
    client, _, _, SessionLocal = test_app
    resp = client.post("/projects", json={"name": "local-dev", "slug": "local-dev"})
    assert resp.status_code == 200
    pid = resp.json()["id"]
    uuid.UUID(pid)

    with SessionLocal() as session:
        project = session.get(Project, uuid.UUID(pid))
        assert project is not None
        assert project.name == "local-dev"
        assert project.slug == "local-dev"

    dup = client.post("/projects", json={"name": "other", "slug": "local-dev"})
    assert dup.status_code == 400
