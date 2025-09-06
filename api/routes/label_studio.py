from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from api.db import get_db
from core.settings import get_settings
from integrations.label_studio.client import LabelStudioClient
from label_studio.config import build_ls_config
from models import Project, Taxonomy


router = APIRouter()


def _get_latest_taxonomy(db: Session, project_id: uuid.UUID) -> list[dict]:
    tax = db.scalar(
        sa.select(Taxonomy)
        .where(Taxonomy.project_id == project_id)
        .order_by(Taxonomy.version.desc())
        .limit(1)
    )
    if tax is None:
        raise HTTPException(status_code=400, detail="taxonomy missing")
    return [dict(f) for f in tax.fields]


@router.post("/label-studio/bootstrap")
def bootstrap_label_studio(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        proj_uuid = uuid.UUID(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    project = db.get(Project, proj_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    settings = get_settings()
    if not settings.ls_base_url or not settings.ls_api_token:
        raise HTTPException(status_code=500, detail="label studio not configured")

    fields = _get_latest_taxonomy(db, proj_uuid)
    xml = build_ls_config(fields)
    client = LabelStudioClient(settings.ls_base_url, settings.ls_api_token)  # type: ignore[arg-type]
    webhook_url = str(request.app.url_path_for("label_studio_webhook"))
    # If base URL known for this API, attempt to build absolute URL
    if request.base_url:
        webhook_url = str(request.base_url).rstrip("/") + webhook_url
    proj = client.create_or_update_project(project.name, xml, webhook_url)
    # Persist LS project id
    try:
        pid = int(proj.get("id"))
    except Exception:
        raise HTTPException(status_code=502, detail="invalid ls response")
    project.ls_project_id = pid  # type: ignore[attr-defined]
    db.add(project)
    db.commit()
    return JSONResponse(status_code=200, content={"ls_project_id": pid})

