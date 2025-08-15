import hashlib
import mimetypes
import urllib.request
from typing import Any

import sqlalchemy as sa
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.settings import get_settings
from models import Document, DocumentStatus, DocumentVersion, Project
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
