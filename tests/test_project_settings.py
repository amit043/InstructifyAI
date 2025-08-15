from tests.conftest import PROJECT_ID_1


def test_project_settings_update_and_rbac(test_app) -> None:
    client, _, _, _ = test_app
    pid = str(PROJECT_ID_1)

    # defaults
    resp = client.get(f"/projects/{pid}/settings")
    assert resp.status_code == 200
    assert resp.json()["use_rules_suggestor"] is True

    # viewer cannot patch
    forbidden = client.patch(
        f"/projects/{pid}/settings",
        json={"use_rules_suggestor": False},
        headers={"X-Role": "viewer"},
    )
    assert forbidden.status_code == 403

    # curator can patch
    updated = client.patch(
        f"/projects/{pid}/settings",
        json={"use_rules_suggestor": False, "max_suggestions_per_doc": 1},
        headers={"X-Role": "curator"},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["use_rules_suggestor"] is False
    assert body["max_suggestions_per_doc"] == 1

    # confirm persisted
    resp2 = client.get(f"/projects/{pid}/settings")
    assert resp2.json()["use_rules_suggestor"] is False
