from tests.conftest import PROJECT_ID_1


def test_create_and_fetch_taxonomy_versions(test_app):
    client, _, _, _ = test_app
    payload = {
        "fields": [
            {
                "name": "severity",
                "type": "enum",
                "required": True,
                "options": ["low", "high"],
            }
        ]
    }
    r1 = client.put(
        f"/projects/{PROJECT_ID_1}/taxonomy",
        json=payload,
        headers={"X-Role": "curator"},
    )
    assert r1.status_code == 200
    assert r1.json()["version"] == 1

    r2 = client.put(
        f"/projects/{PROJECT_ID_1}/taxonomy",
        json=payload,
        headers={"X-Role": "curator"},
    )
    assert r2.status_code == 200
    assert r2.json()["version"] == 2

    r_latest = client.get(f"/projects/{PROJECT_ID_1}/taxonomy")
    assert r_latest.status_code == 200
    assert r_latest.json()["version"] == 2

    r_v1 = client.get(f"/projects/{PROJECT_ID_1}/taxonomy", params={"version": 1})
    assert r_v1.status_code == 200
    assert r_v1.json()["version"] == 1


def test_duplicate_field_name_conflict(test_app):
    client, _, _, _ = test_app
    payload = {
        "fields": [
            {"name": "a", "type": "string"},
            {"name": "a", "type": "string"},
        ]
    }
    r = client.put(
        f"/projects/{PROJECT_ID_1}/taxonomy",
        json=payload,
        headers={"X-Role": "curator"},
    )
    assert r.status_code == 409
