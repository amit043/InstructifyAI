import hashlib
import mimetypes
import urllib.request
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
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from api.schemas import (
    BulkApplyPayload,
    ExportPayload,
    ExportResponse,
    TaxonomyCreate,
    TaxonomyResponse,
    WebhookPayload,
)
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
        project_id = project_field if isinstance(project_field, str) else None
        if not isinstance(upload, UploadFile) or project_id is None:
            raise HTTPException(status_code=400, detail="project_id and file required")
        data = await upload.read()
        filename = upload.filename or "upload"
        mime = (
            upload.content_type
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )
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

    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    doc_hash = hashlib.sha256(data).hexdigest()
    existing = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.project_id == project_id,
            DocumentVersion.doc_hash == doc_hash,
        )
    )
    if existing is not None:
        return {"doc_id": str(existing.document_id)}

    source_type = "html" if "html" in mime else "pdf" if "pdf" in mime else "other"
    document = Document(project_id=project_id, source_type=source_type)
    db.add(document)
    db.flush()

    version = DocumentVersion(
        document_id=document.id,
        project_id=project_id,
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
    parse_document.delay(str(document.id))
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
        query = query.where(Document.project_id == project_id)
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


@app.post("/projects/{project_id}/taxonomy", response_model=TaxonomyResponse)
def create_taxonomy(
    project_id: str,
    payload: TaxonomyCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> TaxonomyResponse:
    latest = db.scalar(
        select(sa.func.max(Taxonomy.version)).where(Taxonomy.project_id == project_id)
    )
    version = (latest or 0) + 1
    tax = Taxonomy(
        project_id=project_id,
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
    query = select(Taxonomy).where(Taxonomy.project_id == project_id)
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
    chunk.meta.update(payload.metadata)
    chunk.rev += 1
    audit = Audit(
        chunk_id=chunk.id,
        user=payload.user,
        action="ls_webhook",
        before=before,
        after=chunk.meta,
    )
    db.add(audit)
    db.commit()
    return {"status": "ok"}


@app.post("/chunks/bulk-apply")
def bulk_apply(
    payload: BulkApplyPayload,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> dict[str, int]:
    for cid in payload.chunk_ids:
        chunk = db.get(Chunk, cid)
        if chunk is None:
            continue
        before = dict(chunk.meta)
        chunk.meta.update(payload.metadata)
        chunk.rev += 1
        audit = Audit(
            chunk_id=chunk.id,
            user=payload.user,
            action="bulk_apply",
            before=before,
            after=chunk.meta,
        )
        db.add(audit)
    db.commit()
    return {"updated": len(payload.chunk_ids)}


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
