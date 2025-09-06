import base64
import hashlib
import hmac
import json

from fastapi import Header, HTTPException

from core.settings import get_settings


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _decode_jwt(token: str, secret: str) -> dict:
    header_b64, payload_b64, signature_b64 = token.split(".")
    signing_input = f"{header_b64}.{payload_b64}".encode()
    expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    actual = _b64url_decode(signature_b64)
    if not hmac.compare_digest(expected, actual):
        raise ValueError("invalid signature")
    header = json.loads(_b64url_decode(header_b64).decode())
    if header.get("alg") != "HS256":
        raise ValueError("unsupported alg")
    return json.loads(_b64url_decode(payload_b64).decode())


def get_current_role(
    authorization: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
) -> str:
    settings = get_settings()
    if settings.env == "DEV" and x_role:
        return x_role
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="forbidden")
    token = authorization.split(" ", 1)[1]
    try:
        payload = _decode_jwt(token, settings.jwt_secret)
    except Exception:
        raise HTTPException(status_code=403, detail="forbidden")
    role = payload.get("role")
    if role not in {"viewer", "curator"}:
        raise HTTPException(status_code=403, detail="forbidden")
    return role
