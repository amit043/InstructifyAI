def test_delete_restore_and_listing_behavior(test_app) -> None:
    client, _, _, _ = test_app
    resp = client.post("/projects", json={"name": "Soft", "slug": "soft"})
    pid = resp.json()["id"]
    resp_ing = client.post(
        "/ingest",
        data={"project_id": pid},
        files={"file": ("a.pdf", b"alpha", "application/pdf")},
    )
    assert resp_ing.status_code == 200
    del_resp = client.delete(
        f"/projects/{pid}?soft=true", headers={"X-Role": "curator"}
    )
    assert del_resp.status_code == 200
    fail_ing = client.post(
        "/ingest",
        data={"project_id": pid},
        files={"file": ("b.pdf", b"beta", "application/pdf")},
    )
    assert fail_ing.status_code == 400
    resp_list = client.get("/projects", headers={"X-Role": "viewer"})
    ids = {p["id"] for p in resp_list.json()["projects"]}
    assert pid not in ids
    resp_all = client.get(
        "/projects?include_deleted=true", headers={"X-Role": "viewer"}
    )
    all_projects = resp_all.json()["projects"]
    assert any(p["id"] == pid and p["is_active"] is False for p in all_projects)
    resp_docs = client.get("/documents", params={"project_id": pid})
    assert resp_docs.json()["total"] == 0
    resp_docs_all = client.get(
        "/documents", params={"project_id": pid, "include_deleted": True}
    )
    assert resp_docs_all.json()["total"] == 1
    res_restore = client.post(f"/projects/{pid}/restore", headers={"X-Role": "curator"})
    assert res_restore.status_code == 200
    resp_ing2 = client.post(
        "/ingest",
        data={"project_id": pid},
        files={"file": ("c.pdf", b"gamma", "application/pdf")},
    )
    assert resp_ing2.status_code == 200
    resp_list2 = client.get("/projects", headers={"X-Role": "viewer"})
    ids2 = {p["id"] for p in resp_list2.json()["projects"]}
    assert pid in ids2
