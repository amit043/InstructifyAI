from datetime import datetime
from typing import Any, List, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TaxonomyField(BaseModel):
    name: str
    type: Literal["string", "enum", "bool", "number", "date"]
    required: bool = False
    helptext: str | None = None
    examples: List[str] | None = None
    options: List[str] | None = None


class TaxonomyCreate(BaseModel):
    fields: List[TaxonomyField]


class TaxonomyResponse(TaxonomyCreate):
    version: int


class GuidelineField(BaseModel):
    field: str
    type: Literal["string", "enum", "bool", "number", "date"]
    required: bool = False
    helptext: str | None = None
    examples: List[str] | None = None


class WebhookPayload(BaseModel):
    chunk_id: str
    user: str
    metadata: dict[str, Any]


class SelectionRange(BaseModel):
    from_: int = Field(..., alias="from")
    to: int


class BulkApplySelection(BaseModel):
    doc_id: str | None = None
    range: SelectionRange | None = None
    chunk_ids: List[str] | None = None


class BulkApplyPatch(BaseModel):
    metadata: dict[str, Any]


class BulkApplyPayload(BaseModel):
    selection: BulkApplySelection
    patch: BulkApplyPatch
    user: str


class AcceptSuggestionPayload(BaseModel):
    user: str


class BulkAcceptSuggestionPayload(BaseModel):
    chunk_ids: List[str]
    field: str
    user: str


class ProjectCreate(BaseModel):
    name: str
    slug: str


class ProjectResponse(BaseModel):
    id: str


class ProjectSummary(BaseModel):
    id: UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime


class ProjectsListResponse(BaseModel):
    projects: List[ProjectSummary]
    total: int


class HtmlCrawlLimits(BaseModel):
    max_depth: int
    max_pages: int


class ProjectSettings(BaseModel):
    use_rules_suggestor: bool = True
    use_mini_llm: bool = False
    max_suggestions_per_doc: int = 200
    suggestion_timeout_ms: int = 500
    ocr_langs: List[str] = Field(default_factory=list)
    min_text_len_for_ocr: int = 0
    html_crawl_limits: HtmlCrawlLimits = Field(
        default_factory=lambda: HtmlCrawlLimits(max_depth=2, max_pages=10)
    )


class ProjectSettingsUpdate(BaseModel):
    use_rules_suggestor: bool | None = None
    use_mini_llm: bool | None = None
    max_suggestions_per_doc: int | None = None
    suggestion_timeout_ms: int | None = None
    ocr_langs: List[str] | None = None
    min_text_len_for_ocr: int | None = None
    html_crawl_limits: HtmlCrawlLimits | None = None


class ExportPayload(BaseModel):
    project_id: str
    doc_ids: List[str] | None = None
    template: str | None = None
    preset: str | None = None
    filters: dict | None = None
    drop_near_dupes: bool = False
    dupe_threshold: float = 0.85


class ExportResponse(BaseModel):
    export_id: str
    url: str


class MetricsResponse(BaseModel):
    curation_completeness: float


class CrawlPayload(BaseModel):
    project_id: str
    base_url: str
    allow_prefix: str | None = None
    max_depth: int
    max_pages: int
