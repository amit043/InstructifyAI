from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
import uuid

from api.deps import require_curator, require_viewer
from api.db import get_db
from registry.adapters import Adapter, get_active_adapter, activate_adapter


router = APIRouter(prefix="/adapters", tags=["adapters"])


class ActivatePayload(BaseModel):
    project_id: str
    adapter_id: str


@router.get("")
def list_adapters(project_id: str, db: Session = Depends(get_db), _: None = Depends(require_viewer)):
    pid = uuid.UUID(project_id)
    q = sa.select(Adapter).where(Adapter.project_id == pid)
    rows = db.execute(q).scalars().all()
    active = get_active_adapter(db, project_id)
    return {
        "items": [
            {"id": str(r.id), "name": r.name, "is_active": r.is_active, "base_model": r.base_model}
            for r in rows
        ],
        "active_adapter_id": str(active.id) if active else None,
    }


@router.post("/activate")
def activate(payload: ActivatePayload, db: Session = Depends(get_db), _: None = Depends(require_curator)):
    if db.get(Adapter, payload.adapter_id) is None:
        raise HTTPException(status_code=404, detail="adapter not found")
    activate_adapter(db, project_id=payload.project_id, adapter_id=payload.adapter_id)
    return {"ok": True}
