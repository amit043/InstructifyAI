import base64
import hmac
import json
import time
from hashlib import sha256

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middleware.rate_limit import RateLimitMiddleware
from core.auth import require_role, verify_jwt
from core.settings import get_settings
from storage.object_store import ObjectStore, signed_url


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _hs256_jwt(payload: dict, secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h}.{p}".encode()
    sig = hmac.new(secret.encode(), signing_input, sha256).digest()
    s = _b64url(sig)
    return f"{h}.{p}.{s}"


def test_verify_jwt_dev_allows_x_role() -> None:
    settings = get_settings()
    settings.env = "DEV"
    claims = verify_jwt(None, "viewer")
    assert claims["role"] == "viewer"


def test_verify_jwt_hs256_and_require_role_curator() -> None:
    settings = get_settings()
    settings.env = "PROD"
    settings.jwt_secret = "test-secret"
    token = _hs256_jwt({"role": "curator"}, settings.jwt_secret)
    claims = verify_jwt(f"Bearer {token}", None)
    assert claims["role"] == "curator"
    # require_role returns a dependency; call it with explicit claims
    dep = require_role("curator")
    assert dep({"role": "curator"}) == "curator"


def test_signed_url_ttl_clamped(monkeypatch) -> None:
    # Fake S3 client records the expiry used
    class Fake:
        def generate_presigned_url(self, op, Params, ExpiresIn):  # noqa: N803
            return f"https://example.com/{Params['Key']}?X-Amz-Expires={ExpiresIn}"

    store = ObjectStore(client=Fake(), bucket="test")
    url = signed_url(store, "derived/doc1/file.txt", expiry=99999)
    assert "X-Amz-Expires=900" in url  # clamped to 15 minutes


def test_rate_limit_blocks_after_threshold(monkeypatch) -> None:
    # Fake async redis client
    class FakeRedis:
        def __init__(self) -> None:
            self.counts: dict[str, int] = {}

        async def incr(self, key: str) -> int:  # noqa: D401
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

        async def expire(self, key: str, ttl: int) -> None:  # noqa: D401
            return None

    class FakeRedisModule:
        @staticmethod
        def from_url(url: str) -> FakeRedis:  # noqa: D401
            return FakeRedis()

    import api.middleware.rate_limit as rl

    monkeypatch.setattr(rl, "aioredis", FakeRedisModule())
    # Freeze time window
    monkeypatch.setattr(time, "time", lambda: 1000)

    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        redis_url="redis://",
        prefixes=("/ingest",),
        max_requests=2,
        window_seconds=60,
    )

    @app.get("/ingest/test")
    async def _endpoint():  # noqa: D401
        return {"ok": True}

    client = TestClient(app)
    h = {"X-Forwarded-For": "1.2.3.4"}
    assert client.get("/ingest/test", headers=h).status_code == 200
    assert client.get("/ingest/test", headers=h).status_code == 200
    # Third within window gets limited
    assert client.get("/ingest/test", headers=h).status_code == 429

