import base64
import hashlib
import hmac
import json

from core.settings import get_settings
from tests.conftest import PROJECT_ID_1


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(role: str) -> str:
    secret = get_settings().jwt_secret
    header = _b64url(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
    )
    payload = _b64url(json.dumps({"role": role}, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode()
    signature = _b64url(
        hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    )
    return f"{header}.{payload}.{signature}"


def test_curator_required_for_project_settings(test_app):
    client, _, _, _ = test_app
    url = f"/projects/{PROJECT_ID_1}/settings"
    body = {"use_rules_suggestor": True}

    r = client.patch(url, json=body)
    assert r.status_code == 403

    viewer = {"Authorization": f"Bearer {make_token('viewer')}"}
    r2 = client.patch(url, json=body, headers=viewer)
    assert r2.status_code == 403

    curator = {"Authorization": f"Bearer {make_token('curator')}"}
    r3 = client.patch(url, json=body, headers=curator)
    assert r3.status_code == 200


def test_export_requires_curator(test_app):
    client, _, _, _ = test_app
    payload = {
        "project_id": str(PROJECT_ID_1),
        "doc_ids": ["d1"],
        "template": "{{}}",
    }

    r = client.post("/export/jsonl", json=payload)
    assert r.status_code == 403

    viewer = {"Authorization": f"Bearer {make_token('viewer')}"}
    r2 = client.post("/export/jsonl", json=payload, headers=viewer)
    assert r2.status_code == 403

    curator = {"Authorization": f"Bearer {make_token('curator')}"}
    r3 = client.post("/export/jsonl", json=payload, headers=curator)
    assert r3.status_code != 403
