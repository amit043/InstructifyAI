from fastapi import Depends, HTTPException

from core.auth import get_current_role


def require_viewer(role: str = Depends(get_current_role)) -> str:
    return role


def require_curator(role: str = Depends(get_current_role)) -> str:
    if role != "curator":
        raise HTTPException(status_code=403, detail="forbidden")
    return role
