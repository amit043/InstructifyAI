import base64
import hashlib
import hmac
import json

from typing import Literal, Optional

from fastapi import Depends, Header, HTTPException

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
    """Backward-compatible role guard used across the codebase.

    Prefer using require_role(...) for new endpoints.
    """
    claims = verify_jwt(authorization, x_role)
    role = claims.get("role")
    if role not in {"viewer", "curator", "admin"}:
        raise HTTPException(status_code=403, detail="forbidden")
    return role


def verify_jwt(
    authorization: Optional[str] = Header(default=None),
    x_role: Optional[str] = Header(default=None),
) -> dict:
    """Verify JWT and return claims.

    - In DEV, allow X-Role header shortcut.
    - Otherwise require Authorization: Bearer <jwt>.
    - Decode via HS256 shared secret, or RS256 when jwt_public_key is configured and PyJWT is available.
    """
    settings = get_settings()
    if settings.env == "DEV" and x_role:
        return {"role": x_role}
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthorized")
    token = authorization.split(" ", 1)[1]
    # Try PyJWT when public key configured
    pub = getattr(settings, "jwt_public_key", None)
    if pub:
        try:
            import jwt  # type: ignore[import-not-found]

            return jwt.decode(token, pub, algorithms=["RS256"])  # type: ignore[no-any-return]
        except Exception as exc:  # pragma: no cover
            # Fall back to HS256 if secret configured, else fail
            if getattr(settings, "jwt_secret", None):
                try:
                    return _decode_jwt(token, settings.jwt_secret)
                except Exception:
                    raise HTTPException(status_code=401, detail="unauthorized")
            raise HTTPException(status_code=401, detail="unauthorized")
    # HS256 shared secret
    try:
        return _decode_jwt(token, settings.jwt_secret)
    except Exception:
        raise HTTPException(status_code=401, detail="unauthorized")


def require_role(role: Literal["viewer", "curator", "admin"]):
    levels = {"viewer": 0, "curator": 1, "admin": 2}

    def _dep(claims: dict = Depends(verify_jwt)) -> str:
        claim_role = claims.get("role")
        if claim_role not in levels:
            raise HTTPException(status_code=403, detail="forbidden")
        if levels[claim_role] < levels[role]:
            raise HTTPException(status_code=403, detail="forbidden")
        return claim_role

    return _dep
