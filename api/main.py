import csv
import hashlib
import io
import mimetypes
import urllib.request
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from api.schemas import (
    AcceptSuggestionPayload,
    BulkAcceptSuggestionPayload,
    BulkApplyPayload,
    ExportPayload,
    ExportResponse,
    MetricsResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectSettings,
    ProjectSettingsUpdate,
    TaxonomyCreate,
    TaxonomyResponse,
    WebhookPayload,
)
from core.correlation import get_request_id, new_request_id, set_request_id
from core.metrics import compute_curation_completeness, enforce_quality_gates
from core.settings import get_settings
from exporters import export_csv, export_jsonl
from models import (
    Audit,
    Chunk,
    Document,
    DocumentStatus,
    DocumentVersion,
    Project,
    Taxonomy,
)
from storage.object_store import ObjectStore, create_client, raw_key
from worker.main import parse_document

settings = get_settings()
engine = sa.create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

app = FastAPI()


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or new_request_id()
    set_request_id(rid)
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


def get_db() -> Any:
    with SessionLocal() as session:
        yield session


def get_object_store() -> ObjectStore:
    client = create_client(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    return ObjectStore(client=client, bucket=settings.s3_bucket)


def get_role(x_role: str | None = Header(default="viewer")) -> str:
    return x_role or "viewer"


def require_curator(role: str = Depends(get_role)) -> str:
    if role != "curator":
        raise HTTPException(status_code=403, detail="forbidden")
    return role


@app.post("/projects", response_model=ProjectResponse)
def create_project_endpoint(
    payload: ProjectCreate, db: Session = Depends(get_db)
) -> ProjectResponse:
    project = Project(name=payload.name, slug=payload.slug)
    db.add(project)
    try:
        db.commit()
    except sa.exc.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="slug already exists")
    return ProjectResponse(id=str(project.id))


@app.get("/projects/{project_id}/settings", response_model=ProjectSettings)
def get_project_settings_endpoint(
    project_id: str, db: Session = Depends(get_db)
) -> ProjectSettings:
    try:
        project_uuid = uuid.UUID(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    project = db.get(Project, project_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return ProjectSettings(
        use_rules_suggestor=project.use_rules_suggestor,
        use_mini_llm=project.use_mini_llm,
        max_suggestions_per_doc=project.max_suggestions_per_doc,
        suggestion_timeout_ms=project.suggestion_timeout_ms,
    )


@app.patch(
    "/projects/{project_id}/settings",
    response_model=ProjectSettings,
    dependencies=[Depends(require_curator)],
)
def update_project_settings_endpoint(
    project_id: str,
    payload: ProjectSettingsUpdate,
    db: Session = Depends(get_db),
) -> ProjectSettings:
    try:
        project_uuid = uuid.UUID(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    project = db.get(Project, project_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return ProjectSettings(
        use_rules_suggestor=project.use_rules_suggestor,
        use_mini_llm=project.use_mini_llm,
        max_suggestions_per_doc=project.max_suggestions_per_doc,
        suggestion_timeout_ms=project.suggestion_timeout_ms,
    )


@app.post("/ingest")
async def ingest(
    request: Request,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
) -> dict[str, str]:
    data: bytes
    filename: str
    mime: str
    project_id: str | None

    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        project_field = form.get("project_id")
        project_id = str(project_field) if project_field is not None else None
        if upload is None or project_id is None:
            raise HTTPException(status_code=400, detail="project_id and file required")
        if hasattr(upload, "read"):
            data = await upload.read()  # type: ignore[call-arg]
            filename = getattr(upload, "filename", "upload") or "upload"
            mime = (
                getattr(upload, "content_type", None)
                or mimetypes.guess_type(filename)[0]
                or "application/octet-stream"
            )
        else:
            if isinstance(upload, (bytes, bytearray)):
                data = bytes(upload)
            elif isinstance(upload, str):
                data = upload.encode()
            else:
                data = bytes(upload)
            filename = "upload"
            mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    else:
        payload = await request.json()
        project_id = payload.get("project_id")
        uri = payload.get("uri")
        if project_id is None or uri is None:
            raise HTTPException(status_code=400, detail="project_id and uri required")
        with urllib.request.urlopen(uri) as resp:  # noqa: S310
            data = resp.read()
            mime = resp.headers.get_content_type()
        filename = uri.split("/")[-1]

    try:
        project_uuid = uuid.UUID(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    project = db.get(Project, project_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    doc_hash = hashlib.sha256(data).hexdigest()
    existing = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.project_id == project_uuid,
            DocumentVersion.doc_hash == doc_hash,
        )
    )
    if existing is not None:
        return {"doc_id": str(existing.document_id)}

    source_type = "html" if "html" in mime else "pdf" if "pdf" in mime else "other"
    document = Document(project_id=project_uuid, source_type=source_type)
    db.add(document)
    db.flush()

    version = DocumentVersion(
        document_id=document.id,
        project_id=project_uuid,
        version=1,
        doc_hash=doc_hash,
        mime=mime,
        size=len(data),
        status=DocumentStatus.INGESTED.value,
        meta={},
    )
    db.add(version)
    db.flush()
    document.latest_version_id = version.id
    db.commit()

    store.put_bytes(raw_key(str(document.id), filename), data)
    parse_document.delay(str(document.id), request_id=get_request_id())
    return {"doc_id": str(document.id)}


@app.get("/documents")
def list_documents(
    project_id: str | None = None,
    type: str | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    query = select(Document, DocumentVersion).join(
        DocumentVersion, DocumentVersion.id == Document.latest_version_id
    )
    if project_id:
        try:
            proj_uuid = uuid.UUID(project_id)
        except Exception:
            raise HTTPException(status_code=400, detail="invalid project_id")
        query = query.where(Document.project_id == proj_uuid)
    if type:
        query = query.where(Document.source_type == type)
    if status:
        query = query.where(DocumentVersion.status == status)
    if q:
        query = query.where(sa.cast(DocumentVersion.meta, sa.String).ilike(f"%{q}%"))
    total = db.scalar(select(sa.func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(Document.id).offset(offset).limit(limit)).all()
    documents = [
        {
            "id": str(doc.id),
            "project_id": str(doc.project_id),
            "type": doc.source_type,
            "status": ver.status,
            "metadata": ver.meta,
        }
        for doc, ver in rows
    ]
    return {"documents": documents, "total": total or 0}


@app.get("/documents/{doc_id}")
def get_document(doc_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    doc = db.get(Document, doc_id)
    if doc is None or doc.latest_version is None:
        raise HTTPException(status_code=404, detail="document not found")
    ver = doc.latest_version
    return {
        "id": str(doc.id),
        "project_id": str(doc.project_id),
        "type": doc.source_type,
        "status": ver.status,
        "metadata": ver.meta,
    }


@app.get("/documents/{doc_id}/chunks")
def list_chunks(
    doc_id: str,
    offset: int = 0,
    limit: int = 50,
    q: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    doc = db.get(Document, doc_id)
    if doc is None or doc.latest_version is None:
        raise HTTPException(status_code=404, detail="document not found")
    ver = doc.latest_version.version
    query = select(Chunk).where(Chunk.document_id == doc_id, Chunk.version == ver)
    if q:
        query = query.where(
            sa.or_(
                sa.cast(Chunk.content, sa.String).ilike(f"%{q}%"),
                sa.cast(Chunk.meta, sa.String).ilike(f"%{q}%"),
            )
        )
    total = db.scalar(select(sa.func.count()).select_from(query.subquery()))
    rows = (
        db.execute(query.order_by(Chunk.order).offset(offset).limit(limit))
        .scalars()
        .all()
    )
    chunks = [
        {
            "id": ch.id,
            "order": ch.order,
            "content": ch.content,
            "metadata": ch.meta,
            "rev": ch.rev,
        }
        for ch in rows
    ]
    return {"chunks": chunks, "total": total or 0}


@app.post("/projects/{project_id}/taxonomy", response_model=TaxonomyResponse)
def create_taxonomy(
    project_id: str,
    payload: TaxonomyCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> TaxonomyResponse:
    try:
        proj_uuid = uuid.UUID(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    latest = db.scalar(
        select(sa.func.max(Taxonomy.version)).where(Taxonomy.project_id == proj_uuid)
    )
    version = (latest or 0) + 1
    tax = Taxonomy(
        project_id=proj_uuid,
        version=version,
        fields=[field.dict() for field in payload.fields],
    )
    db.add(tax)
    db.commit()
    return TaxonomyResponse(version=version, fields=payload.fields)


@app.get("/projects/{project_id}/taxonomy", response_model=TaxonomyResponse)
def get_taxonomy(
    project_id: str,
    version: int | None = None,
    db: Session = Depends(get_db),
) -> TaxonomyResponse:
    try:
        proj_uuid = uuid.UUID(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    query = select(Taxonomy).where(Taxonomy.project_id == proj_uuid)
    if version is not None:
        query = query.where(Taxonomy.version == version)
    else:
        query = query.order_by(Taxonomy.version.desc()).limit(1)
    tax = db.scalar(query)
    if tax is None:
        raise HTTPException(status_code=404, detail="taxonomy not found")
    return TaxonomyResponse(version=tax.version, fields=tax.fields)


def build_ls_config(fields: list[dict]) -> str:
    lines = ["<View>", '<Text name="text" value="$text"/>']
    for field in fields:
        helptext = field.get("helptext") or ""
        examples = field.get("examples", [])
        help_block = "".join([f"<Example>{e}</Example>" for e in examples])
        if helptext or help_block:
            help_block = f"<Help>{helptext}</Help>" + help_block
        if field["type"] == "enum":
            lines.append(f'<Choices name="{field["name"]}" toName="text">')
            if help_block:
                lines.append(help_block)
            for opt in field.get("options", []):
                lines.append(f'<Choice value="{opt}"/>')
            lines.append("</Choices>")
        else:
            lines.append(f'<TextArea name="{field["name"]}" toName="text">')
            if help_block:
                lines.append(help_block)
            lines.append("</TextArea>")
    lines.append("</View>")
    nl = "\n"
    return nl.join(lines)


@app.get("/projects/{project_id}/ls-config")
def ls_config(project_id: str, db: Session = Depends(get_db)) -> Response:
    tax = get_taxonomy(project_id, db=db)
    xml = build_ls_config([f.dict() for f in tax.fields])
    return Response(content=xml, media_type="application/xml")


@app.post("/webhooks/label-studio")
def label_studio_webhook(
    payload: WebhookPayload,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> dict[str, str]:
    chunk = db.get(Chunk, payload.chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="chunk not found")
    before = dict(chunk.meta)
    new_meta = dict(chunk.meta)
    new_meta.update(payload.metadata)
    chunk.meta = new_meta
    chunk.rev += 1
    db.flush()
    audit = Audit(
        chunk_id=chunk.id,
        user=payload.user,
        action="ls_webhook",
        before=before,
        after=new_meta,
        request_id=get_request_id(),
    )
    db.add(audit)
    doc = db.get(Document, chunk.document_id)
    if doc is not None:
        enforce_quality_gates(doc.id, doc.project_id, chunk.version, db)
    db.commit()
    return {"status": "ok"}


@app.post("/chunks/bulk-apply")
def bulk_apply(
    payload: BulkApplyPayload,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> dict[str, int]:
    affected: set[tuple[str, uuid.UUID, int]] = set()
    for cid in payload.chunk_ids:
        chunk = db.get(Chunk, cid)
        if chunk is None:
            continue
        before = dict(chunk.meta)
        new_meta = dict(chunk.meta)
        new_meta.update(payload.metadata)
        chunk.meta = new_meta
        chunk.rev += 1
        db.flush()
        audit = Audit(
            chunk_id=chunk.id,
            user=payload.user,
            action="bulk_apply",
            before=before,
            after=new_meta,
            request_id=get_request_id(),
        )
        db.add(audit)
        doc = db.get(Document, chunk.document_id)
        if doc is not None:
            affected.add((doc.id, doc.project_id, chunk.version))
    for doc_id, proj_id, ver in affected:
        enforce_quality_gates(doc_id, proj_id, ver, db)
    db.commit()
    return {"updated": len(payload.chunk_ids)}


@app.post("/chunks/{chunk_id}/suggestions/{field}/accept")
def accept_suggestion(
    chunk_id: str,
    field: str,
    payload: AcceptSuggestionPayload,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> dict[str, str]:
    chunk = db.get(Chunk, chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="chunk not found")
    suggestions = dict(chunk.meta.get("suggestions", {}))
    suggestion = suggestions.get(field)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="suggestion not found")
    before = dict(chunk.meta)
    new_meta = dict(chunk.meta)
    new_meta[field] = suggestion["value"]
    suggestions.pop(field)
    if suggestions:
        new_meta["suggestions"] = suggestions
    else:
        new_meta.pop("suggestions", None)
    chunk.meta = new_meta
    chunk.rev += 1
    db.flush()
    audit = Audit(
        chunk_id=chunk.id,
        user=payload.user,
        action="accept_suggestion",
        before=before,
        after=new_meta,
        request_id=get_request_id(),
    )
    db.add(audit)
    doc = db.get(Document, chunk.document_id)
    if doc is not None:
        enforce_quality_gates(doc.id, doc.project_id, chunk.version, db)
    db.commit()
    return {"status": "ok"}


@app.post("/chunks/accept-suggestions")
def bulk_accept_suggestions(
    payload: BulkAcceptSuggestionPayload,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> dict[str, int]:
    affected: set[tuple[str, uuid.UUID, int]] = set()
    accepted = 0
    for cid in payload.chunk_ids:
        chunk = db.get(Chunk, cid)
        if chunk is None:
            continue
        suggestions = dict(chunk.meta.get("suggestions", {}))
        suggestion = suggestions.get(payload.field)
        if suggestion is None:
            continue
        before = dict(chunk.meta)
        new_meta = dict(chunk.meta)
        new_meta[payload.field] = suggestion["value"]
        suggestions.pop(payload.field)
        if suggestions:
            new_meta["suggestions"] = suggestions
        else:
            new_meta.pop("suggestions", None)
        chunk.meta = new_meta
        chunk.rev += 1
        db.flush()
        audit = Audit(
            chunk_id=chunk.id,
            user=payload.user,
            action="accept_suggestion",
            before=before,
            after=new_meta,
            request_id=get_request_id(),
        )
        db.add(audit)
        accepted += 1
        doc = db.get(Document, chunk.document_id)
        if doc is not None:
            affected.add((doc.id, doc.project_id, chunk.version))
    for doc_id, proj_id, ver in affected:
        enforce_quality_gates(doc_id, proj_id, ver, db)
    db.commit()
    return {"accepted": accepted}


@app.get("/audits", response_model=None)
def list_audits(
    doc_id: str | None = None,
    user: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    accept: str = Header(default="application/json"),
    db: Session = Depends(get_db),
) -> Response:
    query = select(Audit, Chunk.document_id).join(Chunk, Chunk.id == Audit.chunk_id)
    if doc_id:
        query = query.where(Chunk.document_id == doc_id)
    if user:
        query = query.where(Audit.user == user)
    if action:
        query = query.where(Audit.action == action)
    if since:
        query = query.where(Audit.created_at >= since)
    rows = db.execute(query).all()
    entries = [
        {
            "chunk_id": a.chunk_id,
            "doc_id": d,
            "user": a.user,
            "action": a.action,
            "before": a.before,
            "after": a.after,
            "request_id": a.request_id,
            "created_at": a.created_at.isoformat(),
        }
        for a, d in rows
    ]
    if "text/csv" in accept:
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "chunk_id",
                "doc_id",
                "user",
                "action",
                "request_id",
                "created_at",
            ],
        )
        writer.writeheader()
        for e in entries:
            writer.writerow(
                {
                    "chunk_id": e["chunk_id"],
                    "doc_id": e["doc_id"],
                    "user": e["user"],
                    "action": e["action"],
                    "request_id": e["request_id"],
                    "created_at": e["created_at"],
                }
            )
        return Response(content=output.getvalue(), media_type="text/csv")
    return JSONResponse(entries)


@app.get("/documents/{doc_id}/metrics", response_model=MetricsResponse)
def document_metrics(doc_id: str, db: Session = Depends(get_db)) -> MetricsResponse:
    doc = db.get(Document, doc_id)
    if doc is None or doc.latest_version is None:
        raise HTTPException(status_code=404, detail="document not found")
    completeness = compute_curation_completeness(
        doc.id, doc.project_id, doc.latest_version.version, db
    )
    return MetricsResponse(curation_completeness=completeness)


@app.post("/export/jsonl", response_model=ExportResponse)
def export_jsonl_endpoint(
    payload: ExportPayload,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
) -> ExportResponse:
    tax = get_taxonomy(payload.project_id, db=db)
    export_id, url = export_jsonl(
        store,
        doc_ids=payload.doc_ids,
        template=payload.template,
        preset=payload.preset,
        taxonomy_version=tax.version,
        expiry=settings.export_signed_url_expiry_seconds,
    )
    return ExportResponse(export_id=export_id, url=url)


@app.post("/export/csv", response_model=ExportResponse)
def export_csv_endpoint(
    payload: ExportPayload,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
) -> ExportResponse:
    tax = get_taxonomy(payload.project_id, db=db)
    export_id, url = export_csv(
        store,
        doc_ids=payload.doc_ids,
        template=payload.template,
        preset=payload.preset,
        taxonomy_version=tax.version,
        expiry=settings.export_signed_url_expiry_seconds,
    )
    return ExportResponse(export_id=export_id, url=url)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
