import jwt
from fastapi import Header, HTTPException

from core.settings import get_settings


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
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=403, detail="forbidden")
    role = payload.get("role")
    if role not in {"viewer", "curator"}:
        raise HTTPException(status_code=403, detail="forbidden")
    return role
