from typing import Any, List, Literal

from pydantic import BaseModel


class TaxonomyField(BaseModel):
    name: str
    type: Literal["string", "enum", "bool", "number", "date"]
    required: bool = False
    helptext: str | None = None
    examples: List[str] = []
    options: List[str] = []


class TaxonomyCreate(BaseModel):
    fields: List[TaxonomyField]


class TaxonomyResponse(TaxonomyCreate):
    version: int


class WebhookPayload(BaseModel):
    chunk_id: str
    user: str
    metadata: dict[str, Any]


class BulkApplyPayload(BaseModel):
    chunk_ids: List[str]
    user: str
    metadata: dict[str, Any]


class ExportPayload(BaseModel):
    project_id: str
    doc_ids: List[str]
    template: str | None = None
    preset: str | None = None


class ExportResponse(BaseModel):
    export_id: str
    url: str
