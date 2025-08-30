import csv
import hashlib
import io
import json
import mimetypes
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, cast

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
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from api.deps import require_curator, require_viewer
from api.schemas import (
    AcceptSuggestionPayload,
    ActiveLearningEntry,
    BulkAcceptSuggestionPayload,
    BulkApplyPayload,
    CrawlPayload,
    DatasetCreate,
    DatasetResponse,
    ExportPayload,
    ExportResponse,
    GuidelineField,
    HtmlCrawlLimits,
    JobResponse,
    JobsListResponse,
    LSSyncPayload,
    MetricsResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectSettings,
    ProjectSettingsUpdate,
    ProjectsListResponse,
    ProjectSummary,
    ReleaseDiffResponse,
    ReleaseResponse,
    ReleasesListResponse,
    ReleaseSummary,
    ReparsePayload,
    SignedUrlResponse,
    TaxonomyCreate,
    TaxonomyMigrationPayload,
    TaxonomyResponse,
    ValidationPayload,
    ValidationResponse,
    WebhookPayload,
)
from core.active_learning import next_chunks
from core.correlation import get_request_id, new_request_id, set_request_id
from core.logging import configure_logging
from core.metrics import compute_curation_completeness, enforce_quality_gates
from core.notify import get_notifier
from core.quality import audit_action_with_conflict, compute_iaa
from core.security.project_scope import ensure_document_scope, get_project_scope
from core.settings import get_settings
from core.taxonomy_migrations import rename_enum_values
from exporters import export_csv, export_hf, export_jsonl, export_parquet
from exporters.release import (
    build_manifest,
    diff_manifests,
    export_release,
    manifest_hash,
)
from integrations.label_studio_client import LabelStudioClient
from label_studio.config import build_ls_config
from models import (
    Audit,
    Chunk,
    Dataset,
    Document,
    DocumentStatus,
    DocumentVersion,
    Job,
    JobState,
    JobType,
    Project,
    Release,
    Taxonomy,
)
from services.bulk_apply import apply_bulk_metadata
from services.jobs import create_job
from storage.object_store import (
    ObjectStore,
    create_client,
    dataset_csv_key,
    dataset_snapshot_key,
    derived_key,
    raw_bundle_key,
    raw_key,
    signed_url,
    validation_report_key,
)
from worker.main import crawl_document, parse_document

from .metrics import router as metrics_router
from .search import router as search_router

settings = get_settings()
engine = sa.create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

app = FastAPI()
configure_logging()
app.include_router(metrics_router)
app.include_router(search_router)


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


def get_label_studio_client() -> LabelStudioClient:
    if not settings.ls_base_url or not settings.ls_api_token:
        raise HTTPException(status_code=500, detail="label studio not configured")
    return LabelStudioClient(settings.ls_base_url, settings.ls_api_token)


@app.post("/projects", response_model=ProjectResponse)
def create_project_endpoint(
    payload: ProjectCreate, db: Session = Depends(get_db)
) -> ProjectResponse:
    project = Project(
        name=payload.name,
        slug=payload.slug,
        allow_versioning=payload.allow_versioning,
        use_rules_suggestor=payload.use_rules_suggestor,
        use_mini_llm=payload.use_mini_llm,
        max_suggestions_per_doc=payload.max_suggestions_per_doc,
        suggestion_timeout_ms=payload.suggestion_timeout_ms,
        block_pii=payload.block_pii,
        ocr_langs=payload.ocr_langs,
        min_text_len_for_ocr=payload.min_text_len_for_ocr,
        html_crawl_limits=payload.html_crawl_limits,
    )
    db.add(project)
    try:
        db.commit()
    except sa.exc.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="slug already exists")
    db.refresh(project)  # refresh to get updated fields like created_at

    return ProjectResponse(
        id=str(project.id),
        name=project.name,
        slug=project.slug,
        # include other response fields as needed
    )  # type: ignore[call-arg]


@app.get("/projects", response_model=ProjectsListResponse)
def list_projects(
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
    _: str = Depends(require_viewer),
) -> ProjectsListResponse:
    """
    List projects with optional case-insensitive search on name/slug.
    Sorted by created_at DESC.
    """
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="invalid limit")
    if offset < 0:
        raise HTTPException(status_code=400, detail="invalid offset")
    stmt = sa.select(Project)
    if not include_deleted:
        stmt = stmt.where(Project.is_active.is_(True))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            sa.or_(
                sa.func.lower(Project.name).like(like),
                sa.func.lower(Project.slug).like(like),
            )
        )
    total = db.scalar(sa.select(sa.func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Project.created_at.desc()).offset(offset).limit(limit)
    ).all()
    projects = [
        ProjectSummary(
            id=proj.id,
            name=proj.name,
            slug=proj.slug,
            created_at=cast(datetime, proj.created_at),
            updated_at=cast(datetime, proj.created_at),
            is_active=proj.is_active,
        )
        for proj in rows
    ]
    return ProjectsListResponse(projects=projects, total=total)


@app.delete("/projects/{project_id}")
def delete_project(
    project_id: str,
    soft: bool = False,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> dict[str, str]:
    try:
        project_uuid = uuid.UUID(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    project = db.get(Project, project_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if soft:
        project.deleted_at = datetime.now(timezone.utc)  # type: ignore[assignment]
        project.is_active = False
        db.commit()
    else:
        db.delete(project)
        db.commit()
    return {"status": "deleted"}


@app.post("/projects/{project_id}/restore")
def restore_project(
    project_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> dict[str, str]:
    try:
        project_uuid = uuid.UUID(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    project = db.get(Project, project_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    project.deleted_at = None  # type: ignore[assignment]
    project.is_active = True
    db.commit()
    return {"status": "restored"}


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
        ocr_langs=project.ocr_langs,
        min_text_len_for_ocr=project.min_text_len_for_ocr,
        html_crawl_limits=(
            HtmlCrawlLimits(**project.html_crawl_limits)
            if project.html_crawl_limits
            else HtmlCrawlLimits(
                max_depth=settings.html_crawl_max_depth,
                max_pages=settings.html_crawl_max_pages,
            )
        ),
        block_pii=project.block_pii,
        parser_pipeline=getattr(project, "parser_pipeline", "v1"),
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
        ocr_langs=project.ocr_langs,
        min_text_len_for_ocr=project.min_text_len_for_ocr,
        html_crawl_limits=(
            HtmlCrawlLimits(**project.html_crawl_limits)
            if project.html_crawl_limits
            else HtmlCrawlLimits(
                max_depth=settings.html_crawl_max_depth,
                max_pages=settings.html_crawl_max_pages,
            )
        ),
        block_pii=project.block_pii,
        parser_pipeline=getattr(project, "parser_pipeline", "v1"),
    )


class NotifySettings(BaseModel):
    webhook_url: str | None = None


@app.post("/projects/{project_id}/notify")
def set_project_notify_endpoint(
    project_id: str,
    payload: NotifySettings,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> dict[str, str]:
    try:
        project_uuid = uuid.UUID(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    project = db.get(Project, project_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    notifier = get_notifier()
    if payload.webhook_url:
        notifier.opt_in(project_id, payload.webhook_url)
    else:
        notifier.opt_out(project_id)
    return {"status": "ok"}


@app.post("/ingest")
async def ingest(
    request: Request,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
    project_scope: uuid.UUID | None = Depends(get_project_scope),
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
    if project_scope and project_scope != project_uuid:
        raise HTTPException(status_code=403, detail="forbidden")
    project = db.get(Project, project_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if not project.is_active:
        raise HTTPException(status_code=400, detail="project is inactive")

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
        meta={"filename": filename},
    )
    db.add(version)
    db.flush()
    document.latest_version_id = version.id
    db.commit()

    store.put_bytes(raw_key(str(document.id), filename), data)
    job = create_job(db, JobType.PARSE, project_uuid, uuid.UUID(document.id))
    parse_document.delay(
        str(document.id),
        version.version,
        None,
        None,
        False,
        None,
        str(job.id),
        get_request_id(),
    )
    return {"doc_id": str(document.id)}


@app.post("/ingest/zip")
async def ingest_zip(
    request: Request,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
    project_scope: uuid.UUID | None = Depends(get_project_scope),
) -> dict[str, str]:
    form = await request.form()
    upload = form.get("file")
    project_field = form.get("project_id")
    if upload is None or project_field is None:
        raise HTTPException(status_code=400, detail="project_id and file required")
    data = await upload.read()  # type: ignore[call-arg, union-attr]
    try:
        project_uuid = uuid.UUID(str(project_field))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    if project_scope and project_scope != project_uuid:
        raise HTTPException(status_code=403, detail="forbidden")
    project = db.get(Project, project_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if not project.is_active:
        raise HTTPException(status_code=400, detail="project is inactive")
    from io import BytesIO
    from zipfile import ZipFile

    try:
        with ZipFile(BytesIO(data)) as zf:
            html_files = [f for f in zf.namelist() if f.lower().endswith(".html")]
    except Exception:
        raise HTTPException(status_code=400, detail="invalid zip file")

    doc_hash = hashlib.sha256(data).hexdigest()
    existing = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.project_id == project_uuid,
            DocumentVersion.doc_hash == doc_hash,
        )
    )
    if existing is not None:
        return {"doc_id": str(existing.document_id)}

    document = Document(project_id=project_uuid, source_type="html_bundle")
    db.add(document)
    db.flush()

    version = DocumentVersion(
        document_id=document.id,
        project_id=project_uuid,
        version=1,
        doc_hash=doc_hash,
        mime="application/zip",
        size=len(data),
        status=DocumentStatus.INGESTED.value,
        meta={"filename": "bundle.zip", "file_count": len(html_files)},
    )
    db.add(version)
    db.flush()
    document.latest_version_id = version.id
    db.commit()

    store.put_bytes(raw_bundle_key(str(document.id)), data)
    job = create_job(db, JobType.PARSE, project_uuid, uuid.UUID(document.id))
    parse_document.delay(
        str(document.id),
        version.version,
        None,
        None,
        False,
        None,
        str(job.id),
        get_request_id(),
    )
    return {"doc_id": str(document.id)}


@app.post("/ingest/crawl")
def ingest_crawl(
    payload: CrawlPayload,
    db: Session = Depends(get_db),
    project_scope: uuid.UUID | None = Depends(get_project_scope),
) -> dict[str, str]:
    try:
        project_uuid = uuid.UUID(payload.project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    if project_scope and project_scope != project_uuid:
        raise HTTPException(status_code=403, detail="forbidden")
    project = db.get(Project, project_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if not project.is_active:
        raise HTTPException(status_code=400, detail="project is inactive")
    doc_hash = hashlib.sha256(payload.base_url.encode("utf-8")).hexdigest()
    existing = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.project_id == project_uuid,
            DocumentVersion.doc_hash == doc_hash,
        )
    )
    if existing is not None:
        return {"doc_id": str(existing.document_id)}
    document = Document(project_id=project_uuid, source_type="html_crawl")
    db.add(document)
    db.flush()
    version = DocumentVersion(
        document_id=document.id,
        project_id=project_uuid,
        version=1,
        doc_hash=doc_hash,
        mime="application/x-crawl",
        size=0,
        status=DocumentStatus.INGESTED.value,
        meta={"filename": "crawl/crawl_index.json", "base_url": payload.base_url},
    )
    db.add(version)
    db.flush()
    document.latest_version_id = version.id
    db.commit()
    job = create_job(db, JobType.PARSE, project_uuid, uuid.UUID(document.id))
    crawl_document.delay(
        str(document.id),
        payload.base_url,
        payload.allow_prefix,
        payload.max_depth,
        payload.max_pages,
        request_id=get_request_id(),
        job_id=str(job.id),
    )
    return {"doc_id": str(document.id)}


def _serialize_job(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        type=job.type.value if isinstance(job.type, JobType) else job.type,
        project_id=job.project_id,
        doc_id=job.doc_id,
        state=job.state.value if isinstance(job.state, JobState) else job.state,
        progress=job.progress,
        celery_task_id=job.celery_task_id,
        artifacts=job.artifacts or {},
        error=job.error,
        created_at=cast(datetime, job.created_at),
        updated_at=cast(datetime, job.updated_at),
    )


def _serialize_dataset(dataset: Dataset) -> DatasetResponse:
    return DatasetResponse(
        id=dataset.id,
        project_id=dataset.project_id,
        name=dataset.name,
        filters=dataset.filters or {},
        snapshot_uri=dataset.snapshot_uri,
        stats=dataset.stats or {},
        created_at=cast(datetime, dataset.created_at),
        updated_at=cast(datetime, dataset.updated_at),
    )


def _validate_dataset_bytes(data: bytes) -> tuple[dict[str, int], list[str]]:
    metrics = {"rows": 0, "chars": 0, "docs": 0}
    issues: list[str] = []
    seen_ids: set[str] = set()
    seen_orders: set[tuple[str, int]] = set()
    docs: set[str] = set()
    for line in data.decode("utf-8").splitlines():
        if not line.strip():
            continue
        metrics["rows"] += 1
        try:
            obj = json.loads(line)
        except Exception:
            issues.append("invalid json line")
            continue
        cid = obj.get("chunk_id")
        if cid in seen_ids:
            issues.append(f"duplicate chunk_id {cid}")
        else:
            seen_ids.add(cid)
        doc_id = obj.get("doc_id")
        order = obj.get("order")
        if (doc_id, order) in seen_orders:
            issues.append(f"duplicate order {order} in doc {doc_id}")
        else:
            seen_orders.add((doc_id, order))
        content = obj.get("content")
        if not isinstance(content, dict):
            issues.append(f"invalid content for {cid}")
        else:
            if content.get("type") == "text":
                metrics["chars"] += len(content.get("text", ""))
        metadata = obj.get("metadata")
        if not isinstance(metadata, dict):
            issues.append(f"invalid metadata for {cid}")
        else:
            for k, v in metadata.items():
                if isinstance(v, str) and v.strip() == "":
                    issues.append(f"empty label {k} in chunk {cid}")
        docs.add(doc_id)
    metrics["docs"] = len(docs)
    return metrics, issues


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_viewer),
) -> JobResponse:
    try:
        jid = uuid.UUID(job_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid job_id")
    job = db.get(Job, jid)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _serialize_job(job)


@app.get("/jobs", response_model=JobsListResponse)
def list_jobs(
    project_id: str | None = None,
    type: str | None = None,
    state: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: str = Depends(require_viewer),
) -> JobsListResponse:
    stmt = sa.select(Job)
    if project_id:
        try:
            stmt = stmt.where(Job.project_id == uuid.UUID(project_id))
        except Exception:
            raise HTTPException(status_code=400, detail="invalid project_id")
    if type:
        stmt = stmt.where(Job.type == type)
    if state:
        stmt = stmt.where(Job.state == state)
    total = db.scalar(sa.select(sa.func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Job.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return JobsListResponse(jobs=[_serialize_job(r) for r in rows], total=total)


@app.get("/documents")
def list_documents(
    project_id: str | None = None,
    type: str | None = None,
    status: str | None = None,
    q: str | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    project_scope: uuid.UUID | None = Depends(get_project_scope),
) -> dict[str, Any]:
    query = (
        select(Document, DocumentVersion)
        .join(DocumentVersion, DocumentVersion.id == Document.latest_version_id)
        .join(Project, Project.id == Document.project_id)
    )
    if not include_deleted:
        query = query.where(Project.is_active.is_(True))
    if project_scope:
        project_id = project_id or str(project_scope)
        try:
            proj_uuid = uuid.UUID(project_id)
        except Exception:
            raise HTTPException(status_code=400, detail="invalid project_id")
        if proj_uuid != project_scope:
            raise HTTPException(status_code=403, detail="forbidden")
        query = query.where(Document.project_id == proj_uuid)
    elif project_id:
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
def get_document(
    doc_id: str,
    db: Session = Depends(get_db),
    project_scope: uuid.UUID | None = Depends(get_project_scope),
) -> dict[str, Any]:
    doc = ensure_document_scope(doc_id, db, project_scope)
    if doc.latest_version is None:
        raise HTTPException(status_code=404, detail="document not found")
    ver = doc.latest_version
    return {
        "id": str(doc.id),
        "project_id": str(doc.project_id),
        "type": doc.source_type,
        "status": ver.status,
        "metadata": ver.meta,
    }


@app.get("/documents/{doc_id}/manifest")
def get_document_manifest(
    doc_id: str,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
    project_scope: uuid.UUID | None = Depends(get_project_scope),
) -> dict[str, Any]:
    ensure_document_scope(doc_id, db, project_scope)
    key = derived_key(doc_id, "manifest.json")
    try:
        payload = store.get_bytes(key)
    except Exception:
        raise HTTPException(status_code=404, detail="manifest not found")
    try:
        return json.loads(payload.decode("utf-8"))
    except Exception as exc:  # pragma: no cover - unexpected
        raise HTTPException(status_code=500, detail="invalid manifest") from exc


@app.get("/documents/{doc_id}/chunks")
def stream_chunks(
    doc_id: str,
    offset: int = 0,
    limit: int | None = None,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
    project_scope: uuid.UUID | None = Depends(get_project_scope),
) -> StreamingResponse:
    if offset < 0 or (limit is not None and limit < 0):
        raise HTTPException(status_code=400, detail="invalid offset/limit")
    ensure_document_scope(doc_id, db, project_scope)
    key = derived_key(doc_id, "chunks.jsonl")
    try:
        lines = store.get_bytes(key).decode("utf-8").splitlines()
    except Exception:
        raise HTTPException(status_code=404, detail="chunks not found")
    start = offset
    end = start + limit if limit is not None else None
    slice_lines = lines[start:end]

    def _iter() -> Iterable[str]:
        for line in slice_lines:
            yield line + "\n"

    return StreamingResponse(_iter(), media_type="application/x-ndjson")


@app.post("/documents/{doc_id}/reparse")
def reparse_document(
    doc_id: str,
    force_version_bump: bool = False,
    stages: str | None = None,
    reset_suggestions: bool = True,
    pipeline: str | None = None,
    payload: ReparsePayload | None = None,
    db: Session = Depends(get_db),
    project_scope: uuid.UUID | None = Depends(get_project_scope),
) -> dict[str, Any]:
    doc = ensure_document_scope(doc_id, db, project_scope)
    if doc.latest_version is None:
        raise HTTPException(status_code=404, detail="document not found")
    current = doc.latest_version
    dv = current
    if force_version_bump:
        new_version = current.version + 1
        new_hash = hashlib.sha256(
            f"{current.doc_hash}:{new_version}".encode("utf-8")
        ).hexdigest()
        dv = DocumentVersion(
            document_id=doc.id,
            project_id=doc.project_id,
            version=new_version,
            doc_hash=new_hash,
            mime=current.mime,
            size=current.size,
            status=DocumentStatus.INGESTED.value,
            meta=dict(current.meta),
        )
        db.add(dv)
        db.flush()
        doc.latest_version_id = dv.id
        db.commit()
    stages_list = stages.split(",") if stages else None
    job = create_job(db, JobType.REPARSE, doc.project_id, uuid.UUID(doc.id))
    parse_document.delay(
        doc.id,
        dv.version,
        payload.parser_overrides if payload else None,
        stages_list,
        reset_suggestions,
        pipeline,
        str(job.id),
        get_request_id(),
    )
    return {"job_id": str(job.id), "doc_id": doc.id, "version": dv.version}


@app.put("/projects/{project_id}/taxonomy", response_model=TaxonomyResponse)
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

    seen: set[str] = set()
    for field in payload.fields:
        if field.name in seen:
            raise HTTPException(status_code=409, detail="duplicate field name")
        seen.add(field.name)
        if field.type == "enum" and not field.options:
            raise HTTPException(status_code=400, detail="enum field requires options")
    latest = db.scalar(
        select(sa.func.max(Taxonomy.version)).where(Taxonomy.project_id == proj_uuid)
    )
    version = (latest or 0) + 1
    tax = Taxonomy(
        project_id=proj_uuid,
        version=version,
        fields=[field.dict(exclude_none=True) for field in payload.fields],
    )
    db.add(tax)
    try:
        db.commit()
    except sa.exc.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="taxonomy version exists")
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


@app.patch("/projects/{project_id}/taxonomy")
def patch_taxonomy(
    project_id: str,
    payload: TaxonomyMigrationPayload,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> dict[str, int]:
    count = rename_enum_values(
        db, project_id, payload.field, payload.mapping, payload.user
    )
    return {"migrated": count}


@app.get(
    "/projects/{project_id}/taxonomy/guidelines",
    response_model=list[GuidelineField],
)
def get_taxonomy_guidelines(
    project_id: str,
    accept: str | None = Header(None),
    db: Session = Depends(get_db),
):
    tax = get_taxonomy(project_id, db=db)
    fields = [
        GuidelineField(
            field=f.name,
            type=f.type,
            required=f.required,
            helptext=f.helptext,
            examples=f.examples,
        )
        for f in tax.fields
    ]
    if accept and "text/plain" in accept:
        lines: list[str] = []
        for g in fields:
            header = f"### {g.field} ({g.type})"
            if g.required:
                header += " [required]"
            lines.append(header)
            if g.helptext:
                lines.append(g.helptext)
            if g.examples:
                lines.append("Examples:")
                for ex in g.examples:
                    lines.append(f"- {ex}")
            lines.append("")
        return PlainTextResponse("\n".join(lines).strip() + "\n")
    return fields


@app.post("/label-studio/config")
def label_studio_config(project_id: str, db: Session = Depends(get_db)) -> Response:
    try:
        tax = get_taxonomy(project_id, db=db)
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=400, detail="taxonomy missing")
        raise
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
    new_meta = {**before, **payload.metadata}
    if new_meta == before:
        return {"status": "ok"}
    chunk.meta = new_meta
    chunk.rev += 1
    action = audit_action_with_conflict(
        db, chunk.id, payload.user, "ls_webhook", before, new_meta
    )
    audit = Audit(
        chunk_id=chunk.id,
        user=payload.user,
        action=action,
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


@app.post("/integrations/label-studio/projects/{project_id}/sync")
def sync_label_studio(
    project_id: str,
    payload: LSSyncPayload,
    request: Request,
    db: Session = Depends(get_db),
    client: LabelStudioClient = Depends(get_label_studio_client),
    _: str = Depends(require_curator),
) -> dict[str, Any]:
    try:
        proj_uuid = uuid.UUID(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    project = db.get(Project, proj_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    ls_project = client.upsert_project(project.slug, title=project.name)
    ls_id = int(ls_project["id"])
    try:
        tax = get_taxonomy(project_id, db=db)
        config = build_ls_config([f.dict() for f in tax.fields])
    except HTTPException:
        config = '<View>\n<Text name="text" value="$text"/>\n</View>'
    client.set_project_config(ls_id, config)
    webhook_url = str(request.url_for("label_studio_webhook"))
    client.ensure_webhook(ls_id, webhook_url)
    rows = (
        db.query(Chunk)
        .filter(Chunk.document_id.in_(payload.doc_ids))
        .order_by(Chunk.order)
        .limit(payload.limit)
        .all()
    )
    tasks = [
        {
            "id": c.id,
            "data": {
                "text": c.content.get("text") or "",
                "chunk_id": c.id,
                "doc_id": c.document_id,
            },
        }
        for c in rows
    ]
    pushed = client.create_tasks(ls_id, tasks)
    preview_url = f"{client.base_url}/projects/{ls_id}"
    return {"ls_project_id": ls_id, "pushed": pushed, "preview_url": preview_url}


@app.get("/integrations/label-studio/health")
def label_studio_health(
    request: Request, client: LabelStudioClient = Depends(get_label_studio_client)
) -> dict[str, bool]:
    ok = client.check_connection()
    webhook = client.has_webhook(str(request.url_for("label_studio_webhook")))
    return {"ok": ok, "webhook": webhook}


@app.post("/chunks/bulk-apply")
def bulk_apply(
    payload: BulkApplyPayload,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> dict[str, int]:
    updated = apply_bulk_metadata(db, payload)
    return {"updated": updated}


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
    action = audit_action_with_conflict(
        db, chunk.id, payload.user, "accept_suggestion", before, new_meta
    )
    audit = Audit(
        chunk_id=chunk.id,
        user=payload.user,
        action=action,
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
        action = audit_action_with_conflict(
            db, chunk.id, payload.user, "accept_suggestion", before, new_meta
        )
        audit = Audit(
            chunk_id=chunk.id,
            user=payload.user,
            action=action,
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
    query = (
        select(Audit, Chunk.document_id)
        .join(Chunk, Chunk.id == Audit.chunk_id)
        .order_by(Audit.created_at)
    )
    if doc_id:
        query = query.where(Chunk.document_id == doc_id)
    if user:
        query = query.where(Audit.user == user)
    if action:
        query = query.where(Audit.action == action)
    if since:
        query = query.where(Audit.created_at >= since)
    if "text/csv" in accept.lower():

        def generate() -> Iterable[str]:
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(
                [
                    "chunk_id",
                    "doc_id",
                    "user",
                    "action",
                    "request_id",
                    "created_at",
                ]
            )
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
            for a, d in db.execute(query):
                writer.writerow(
                    [
                        a.chunk_id,
                        d,
                        a.user,
                        a.action,
                        a.request_id,
                        a.created_at.isoformat(),
                    ]
                )
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)

        return StreamingResponse(generate(), media_type="text/csv")

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
    return JSONResponse(entries)


@app.get("/documents/{doc_id}/metrics", response_model=MetricsResponse)
def document_metrics(doc_id: str, db: Session = Depends(get_db)) -> MetricsResponse:
    doc = db.get(Document, doc_id)
    if doc is None or doc.latest_version is None:
        raise HTTPException(status_code=404, detail="document not found")
    completeness = compute_curation_completeness(
        doc.id, doc.project_id, doc.latest_version.version, db
    )
    iaa = compute_iaa(doc.id, doc.latest_version.version, db)
    return MetricsResponse(curation_completeness=completeness, iaa=iaa)


@app.get("/curation/next", response_model=list[ActiveLearningEntry])
def next_for_curation(
    project_id: str,
    limit: int = 10,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> list[ActiveLearningEntry]:
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="invalid limit")
    try:
        entries = next_chunks(project_id, limit, db)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    return [ActiveLearningEntry(chunk_id=c, reasons=r) for c, r in entries]


@app.post("/export/jsonl", response_model=ExportResponse)
def export_jsonl_endpoint(
    payload: ExportPayload,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
    _: str = Depends(require_curator),
    project_scope: uuid.UUID | None = Depends(get_project_scope),
) -> ExportResponse:
    tax = get_taxonomy(payload.project_id, db=db)
    try:
        proj_uuid = uuid.UUID(payload.project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    if project_scope and project_scope != proj_uuid:
        raise HTTPException(status_code=403, detail="forbidden")
    project = db.get(Project, proj_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if not payload.doc_ids:
        raise HTTPException(status_code=400, detail="doc_ids required")
    for doc_id in payload.doc_ids:
        doc = db.get(Document, doc_id)
        if doc is None or doc.project_id != proj_uuid:
            raise HTTPException(status_code=403, detail="forbidden")
    export_id, url = export_jsonl(
        store,
        doc_ids=payload.doc_ids,
        template=payload.template,
        preset=payload.preset,
        taxonomy_version=tax.version,
        filters=payload.filters,
        project=project,
        drop_near_dupes=payload.drop_near_dupes,
        dupe_threshold=payload.dupe_threshold,
        exclude_pii=payload.exclude_pii,
        split=payload.split,
    )
    return ExportResponse(export_id=export_id, url=url)


@app.post("/export/csv", response_model=ExportResponse)
def export_csv_endpoint(
    payload: ExportPayload,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
    _: str = Depends(require_curator),
    project_scope: uuid.UUID | None = Depends(get_project_scope),
) -> ExportResponse:
    tax = get_taxonomy(payload.project_id, db=db)
    try:
        proj_uuid = uuid.UUID(payload.project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    if project_scope and project_scope != proj_uuid:
        raise HTTPException(status_code=403, detail="forbidden")
    project = db.get(Project, proj_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if not payload.doc_ids:
        raise HTTPException(status_code=400, detail="doc_ids required")
    for doc_id in payload.doc_ids:
        doc = db.get(Document, doc_id)
        if doc is None or doc.project_id != proj_uuid:
            raise HTTPException(status_code=403, detail="forbidden")
    export_id, url = export_csv(
        store,
        doc_ids=payload.doc_ids,
        template=payload.template,
        preset=payload.preset,
        taxonomy_version=tax.version,
        filters=payload.filters,
        project=project,
        drop_near_dupes=payload.drop_near_dupes,
        dupe_threshold=payload.dupe_threshold,
        exclude_pii=payload.exclude_pii,
        split=payload.split,
    )
    return ExportResponse(export_id=export_id, url=url)


@app.post("/export/parquet", response_model=ExportResponse)
def export_parquet_endpoint(
    payload: ExportPayload,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
    _: str = Depends(require_curator),
    project_scope: uuid.UUID | None = Depends(get_project_scope),
) -> ExportResponse:
    tax = get_taxonomy(payload.project_id, db=db)
    try:
        proj_uuid = uuid.UUID(payload.project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    if project_scope and project_scope != proj_uuid:
        raise HTTPException(status_code=403, detail="forbidden")
    project = db.get(Project, proj_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if not payload.doc_ids:
        raise HTTPException(status_code=400, detail="doc_ids required")
    for doc_id in payload.doc_ids:
        doc = db.get(Document, doc_id)
        if doc is None or doc.project_id != proj_uuid:
            raise HTTPException(status_code=403, detail="forbidden")
    export_id, url = export_parquet(
        store,
        doc_ids=payload.doc_ids,
        template=payload.template,
        preset=payload.preset,
        taxonomy_version=tax.version,
        filters=payload.filters,
        project=project,
        drop_near_dupes=payload.drop_near_dupes,
        dupe_threshold=payload.dupe_threshold,
        exclude_pii=payload.exclude_pii,
        split=payload.split,
    )
    return ExportResponse(export_id=export_id, url=url)


@app.post("/export/hf", response_model=ExportResponse)
def export_hf_endpoint(
    payload: ExportPayload,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
    _: str = Depends(require_curator),
    project_scope: uuid.UUID | None = Depends(get_project_scope),
) -> ExportResponse:
    tax = get_taxonomy(payload.project_id, db=db)
    try:
        proj_uuid = uuid.UUID(payload.project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    if project_scope and project_scope != proj_uuid:
        raise HTTPException(status_code=403, detail="forbidden")
    project = db.get(Project, proj_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if not payload.doc_ids:
        raise HTTPException(status_code=400, detail="doc_ids required")
    for doc_id in payload.doc_ids:
        doc = db.get(Document, doc_id)
        if doc is None or doc.project_id != proj_uuid:
            raise HTTPException(status_code=403, detail="forbidden")
    export_id, url = export_hf(
        store,
        doc_ids=payload.doc_ids,
        template=payload.template,
        preset=payload.preset,
        taxonomy_version=tax.version,
        filters=payload.filters,
        project=project,
        drop_near_dupes=payload.drop_near_dupes,
        dupe_threshold=payload.dupe_threshold,
        exclude_pii=payload.exclude_pii,
        split=payload.split,
    )
    return ExportResponse(export_id=export_id, url=url)


@app.post("/projects/{project_id}/releases", response_model=ReleaseResponse)
def create_release_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> ReleaseResponse:
    try:
        proj_uuid = uuid.UUID(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    project = db.get(Project, proj_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    manifest = build_manifest(db, proj_uuid)
    content_hash = manifest_hash(manifest)
    release = Release(
        project_id=proj_uuid, manifest=manifest, content_hash=content_hash
    )
    db.add(release)
    db.commit()
    return ReleaseResponse(
        id=str(release.id),
        created_at=cast(datetime, release.created_at),
        manifest=manifest,
        content_hash=content_hash,
    )


@app.get("/projects/{project_id}/releases", response_model=ReleasesListResponse)
def list_releases_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_viewer),
) -> ReleasesListResponse:
    try:
        proj_uuid = uuid.UUID(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    rows = db.scalars(
        sa.select(Release)
        .where(Release.project_id == proj_uuid)
        .order_by(Release.created_at.desc())
    ).all()
    releases = [
        ReleaseSummary(
            id=str(r.id),
            created_at=cast(datetime, r.created_at),
            content_hash=r.content_hash,
        )
        for r in rows
    ]
    return ReleasesListResponse(releases=releases)


@app.get("/releases/diff", response_model=ReleaseDiffResponse)
def diff_releases_endpoint(
    base: str,
    compare: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_viewer),
) -> ReleaseDiffResponse:
    try:
        base_id = uuid.UUID(base)
        compare_id = uuid.UUID(compare)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid release id")
    r1 = db.get(Release, base_id)
    r2 = db.get(Release, compare_id)
    if r1 is None or r2 is None:
        raise HTTPException(status_code=404, detail="release not found")
    diff = diff_manifests(r1.manifest, r2.manifest)
    return ReleaseDiffResponse(**diff)


@app.get("/releases/{release_id}", response_model=ReleaseResponse)
def get_release_endpoint(
    release_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_viewer),
) -> ReleaseResponse:
    try:
        rel_uuid = uuid.UUID(release_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid release_id")
    release = db.get(Release, rel_uuid)
    if release is None:
        raise HTTPException(status_code=404, detail="release not found")
    return ReleaseResponse(
        id=str(release.id),
        created_at=cast(datetime, release.created_at),
        manifest=release.manifest,
        content_hash=release.content_hash,
    )


@app.get("/releases/{release_id}/export", response_model=ExportResponse)
def export_release_endpoint(
    release_id: str,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
    _: str = Depends(require_curator),
) -> ExportResponse:
    try:
        rel_uuid = uuid.UUID(release_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid release_id")
    release = db.get(Release, rel_uuid)
    if release is None:
        raise HTTPException(status_code=404, detail="release not found")
    export_id, url = export_release(store, release)
    return ExportResponse(export_id=export_id, url=url)


@app.post("/datasets", response_model=DatasetResponse)
def create_dataset_endpoint(
    payload: DatasetCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_curator),
) -> DatasetResponse:
    try:
        proj_uuid = uuid.UUID(payload.project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid project_id")
    project = db.get(Project, proj_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    dataset = Dataset(
        project_id=proj_uuid,
        name=payload.name,
        filters=payload.filters or {},
        stats={},
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return _serialize_dataset(dataset)


@app.post("/datasets/{dataset_id}/materialize", response_model=DatasetResponse)
def materialize_dataset_endpoint(
    dataset_id: str,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
    _: str = Depends(require_curator),
) -> DatasetResponse:
    try:
        ds_uuid = uuid.UUID(dataset_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid dataset_id")
    dataset = db.get(Dataset, ds_uuid)
    if dataset is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    filters = dataset.filters or {}
    stmt = (
        sa.select(Chunk)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.project_id == dataset.project_id)
    )
    doc_ids = filters.get("doc_ids")
    if doc_ids:
        stmt = stmt.where(Chunk.document_id.in_(doc_ids))
    rows = db.scalars(stmt.order_by(Chunk.document_id, Chunk.order)).all()
    buf = io.StringIO()
    chars = 0
    docs: set[str] = set()
    for r in rows:
        obj = {
            "doc_id": r.document_id,
            "chunk_id": r.id,
            "order": r.order,
            "content": r.content,
            "metadata": r.meta,
        }
        if isinstance(r.content, dict) and r.content.get("type") == "text":
            chars += len(r.content.get("text", ""))
        docs.add(r.document_id)
        buf.write(json.dumps(obj) + "\n")
    key = dataset_snapshot_key(dataset_id)
    store.put_bytes(key, buf.getvalue().encode("utf-8"))
    dataset.snapshot_uri = key
    dataset.stats = {"rows": len(rows), "chars": chars, "docs": len(docs)}
    db.commit()
    db.refresh(dataset)
    return _serialize_dataset(dataset)


@app.get("/datasets/{dataset_id}", response_model=DatasetResponse)
def get_dataset_endpoint(
    dataset_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_viewer),
) -> DatasetResponse:
    try:
        ds_uuid = uuid.UUID(dataset_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid dataset_id")
    dataset = db.get(Dataset, ds_uuid)
    if dataset is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    return _serialize_dataset(dataset)


@app.post("/datasets/{dataset_id}/export", response_model=SignedUrlResponse)
def export_dataset_endpoint(
    dataset_id: str,
    format: str = "jsonl",
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
    _: str = Depends(require_curator),
) -> SignedUrlResponse:
    try:
        ds_uuid = uuid.UUID(dataset_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid dataset_id")
    dataset = db.get(Dataset, ds_uuid)
    if dataset is None or dataset.snapshot_uri is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    key = dataset.snapshot_uri
    if format == "csv":
        lines = store.get_bytes(dataset.snapshot_uri).decode("utf-8").splitlines()
        out = io.StringIO()
        writer = csv.DictWriter(
            out, fieldnames=["doc_id", "chunk_id", "order", "content", "metadata"]
        )
        writer.writeheader()
        for line in lines:
            if not line.strip():
                continue
            obj = json.loads(line)
            writer.writerow(
                {
                    "doc_id": obj.get("doc_id"),
                    "chunk_id": obj.get("chunk_id"),
                    "order": obj.get("order"),
                    "content": json.dumps(obj.get("content")),
                    "metadata": json.dumps(obj.get("metadata")),
                }
            )
        key = dataset_csv_key(dataset_id)
        store.put_bytes(key, out.getvalue().encode("utf-8"))
    elif format != "jsonl":
        raise HTTPException(status_code=400, detail="invalid format")
    url = signed_url(store, key, db=db, project_id=str(dataset.project_id))
    return SignedUrlResponse(url=url)


@app.post("/exports/validate", response_model=ValidationResponse)
def validate_export_endpoint(
    payload: ValidationPayload,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
    _: str = Depends(require_curator),
) -> ValidationResponse:
    if (payload.dataset_id is None) == (payload.url is None):
        raise HTTPException(status_code=400, detail="dataset_id or url required")
    data: bytes
    project_id: str | None = None
    dataset_id = payload.dataset_id
    if payload.dataset_id:
        try:
            ds_uuid = uuid.UUID(payload.dataset_id)
        except Exception:
            raise HTTPException(status_code=400, detail="invalid dataset_id")
        dataset = db.get(Dataset, ds_uuid)
        if dataset is None or dataset.snapshot_uri is None:
            raise HTTPException(status_code=404, detail="dataset not found")
        data = store.get_bytes(dataset.snapshot_uri)
        project_id = str(dataset.project_id)
    else:
        with urllib.request.urlopen(payload.url) as resp:  # type: ignore[arg-type]
            data = resp.read()
    metrics, issues = _validate_dataset_bytes(data)
    status = "passed" if not issues else "failed"
    report = {"status": status, "metrics": metrics, "issues": issues}
    report_id = str(uuid.uuid4())
    if dataset_id:
        key = validation_report_key(dataset_id, report_id)
        store.put_bytes(key, json.dumps(report).encode("utf-8"))
        report_url = signed_url(store, key, db=db, project_id=project_id)
    else:
        key = validation_report_key("external", report_id)
        store.put_bytes(key, json.dumps(report).encode("utf-8"))
        report_url = store.presign_get(key, settings.export_signed_url_expiry_seconds)
    return ValidationResponse(
        status=status, metrics=metrics, issues=issues, report_url=report_url
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/curation-lite/dev")
def curation_lite_dev(_: str = Depends(require_viewer)) -> dict[str, str]:
    """Minimal helper endpoint for Curation Lite UI."""
    return {"status": "curation-lite"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
