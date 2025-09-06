from tests.conftest import PROJECT_ID_1


def test_guidelines_endpoint(test_app):
    client, _, _, _ = test_app
    payload = {
        "fields": [
            {
                "name": "severity",
                "type": "enum",
                "required": True,
                "helptext": "Severity level",
                "examples": ["low", "high"],
                "options": ["low", "high"],
            }
        ]
    }
    r = client.put(
        f"/projects/{PROJECT_ID_1}/taxonomy",
        json=payload,
        headers={"X-Role": "curator"},
    )
    assert r.status_code == 200

    r_json = client.get(f"/projects/{PROJECT_ID_1}/taxonomy/guidelines")
    assert r_json.status_code == 200
    body = r_json.json()
    assert body[0]["helptext"] == "Severity level"
    assert "low" in body[0]["examples"]

    r_text = client.get(
        f"/projects/{PROJECT_ID_1}/taxonomy/guidelines",
        headers={"Accept": "text/plain"},
    )
    assert r_text.status_code == 200
    assert "Severity level" in r_text.text
    assert "- low" in r_text.text
