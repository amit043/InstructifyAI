import uuid

import sqlalchemy as sa

from models import Project


def _clear_projects(SessionLocal) -> None:
    with SessionLocal() as session:
        session.execute(sa.delete(Project))
        session.commit()


def test_list_projects_empty(test_app) -> None:
    client, _, _, SessionLocal = test_app
    _clear_projects(SessionLocal)
    resp = client.get("/projects", headers={"X-Role": "viewer"})
    assert resp.status_code == 200
    assert resp.json() == {"projects": [], "total": 0}


def test_list_projects_returns_project(test_app) -> None:
    client, _, _, SessionLocal = test_app
    _clear_projects(SessionLocal)
    create = client.post("/projects", json={"name": "Alpha", "slug": "alpha"})
    assert create.status_code == 200
    resp = client.get("/projects", headers={"X-Role": "viewer"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    proj = body["projects"][0]
    uuid.UUID(proj["id"])
    assert proj["name"] == "Alpha"
    assert proj["slug"] == "alpha"
    assert proj["created_at"]
    assert proj["updated_at"]


def test_list_projects_pagination(test_app) -> None:
    client, _, _, SessionLocal = test_app
    _clear_projects(SessionLocal)
    for i in range(3):
        client.post("/projects", json={"name": f"P{i}", "slug": f"p{i}"})
    resp1 = client.get("/projects?limit=2&offset=0", headers={"X-Role": "viewer"})
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["total"] == 3
    assert len(data1["projects"]) == 2
    resp2 = client.get("/projects?limit=2&offset=2", headers={"X-Role": "viewer"})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["total"] == 3
    assert len(data2["projects"]) == 1
    first_slugs = {p["slug"] for p in data1["projects"]}
    second_slugs = {p["slug"] for p in data2["projects"]}
    assert not first_slugs & second_slugs


def test_list_projects_search(test_app) -> None:
    client, _, _, SessionLocal = test_app
    _clear_projects(SessionLocal)
    client.post("/projects", json={"name": "Alpha", "slug": "one"})
    client.post("/projects", json={"name": "Beta", "slug": "beta"})
    resp1 = client.get("/projects?q=alpha", headers={"X-Role": "viewer"})
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["total"] == 1
    assert data1["projects"][0]["name"] == "Alpha"
    resp2 = client.get("/projects?q=ONE", headers={"X-Role": "viewer"})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["total"] == 1
    assert data2["projects"][0]["slug"] == "one"


def test_list_projects_invalid_params(test_app) -> None:
    client, _, _, SessionLocal = test_app
    _clear_projects(SessionLocal)
    assert (
        client.get("/projects?limit=0", headers={"X-Role": "viewer"}).status_code == 400
    )
    assert (
        client.get("/projects?limit=1000", headers={"X-Role": "viewer"}).status_code
        == 400
    )
    assert (
        client.get("/projects?offset=-1", headers={"X-Role": "viewer"}).status_code
        == 400
    )
