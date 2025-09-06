from tests.conftest import PROJECT_ID_1

EXPECTED_XML = """<View>
<Text name="text" value="$text"/>
<Choices name="severity" toName="text">
<Help>Severity level</Help>
<Example>low</Example>
<Example>high</Example>
<Choice value="low"/>
<Choice value="high"/>
</Choices>
<TextArea name="notes" toName="text">
</TextArea>
</View>"""


def test_ls_config_snapshot(test_app):
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
            },
            {"name": "notes", "type": "string"},
        ]
    }
    r = client.put(
        f"/projects/{PROJECT_ID_1}/taxonomy",
        json=payload,
        headers={"X-Role": "curator"},
    )
    assert r.status_code == 200
    xml = client.post(
        "/label-studio/config",
        params={"project_id": PROJECT_ID_1},
    )
    assert xml.status_code == 200
    assert xml.text == EXPECTED_XML


def test_ls_config_missing_taxonomy(test_app):
    client, _, _, _ = test_app
    r = client.post("/label-studio/config", params={"project_id": PROJECT_ID_1})
    assert r.status_code == 400
