# Codex Prompt Pack — Phase 1 (v2.1, scope-locked, LS-first)

This **merged pack** combines the original v2 prompts and the addendum into a single, numbered list.
It reflects the agreed scope:
- Phase 1 = metadata/classification curation only (**spans/NER deferred to Phase 1.5**).
- Robust tables deferred to 1.5 (placeholders only).
- **Label Studio first**, no custom React in Phase 1.
- Connectors: **Local upload + S3/MinIO only**.

Each item includes a **Prompt** and **Acceptance** to use directly with your coding assistant.

---

## 1) Docker Compose + Healthchecks
**Prompt:** Create `docker-compose.yml` with services: api (FastAPI on 8000), worker (Celery), postgres, redis, minio (console 9001). Add healthchecks and named volumes.
**Acceptance:** `docker compose up` → `/health` returns 200; all services healthy.

---

## 2) Pydantic Settings Profiles
**Prompt:** Implement `core/settings.py` using pydantic-settings with DEV/TEST/PROD profiles and strict validation.
**Acceptance:** Missing env vars raise clear errors; switching profiles changes defaults.

---

## 3) Object Store Client + Signed URLs
**Prompt:** Implement `storage/object_store.py` for MinIO/S3 with `put_bytes`, `get_bytes`, `presign_get/put(expiry)`. Key scheme: `/raw/{doc_id}/...`, `/derived/{doc_id}/...`, `/exports/{export_id}/...`.
**Acceptance:** Upload/download roundtrip passes; presigned URL expires as configured.

---

## 4) /ingest Endpoint (file or URI) with Dedup
**Prompt:** Build `POST /ingest` for multipart uploads or `{uri}` JSON. Compute SHA256 `doc_hash`; dedup per `(project_id, doc_hash)` unless `allow_versioning`; enqueue `parse_document(doc_id)`.
**Acceptance:** Returns `{doc_id}`; duplicate upload does not enqueue a new parse when `allow_versioning=false`.

---

## 5) Document Listing & Filters
**Prompt:** Implement `GET /documents?project_id=&type=&status=&q=&page=&limit=` with stable pagination and case-insensitive JSONB key search.
**Acceptance:** Filtering by any combination returns expected results; pagination stable under inserts.

---

## 6) ParserRegistry Interface
**Prompt:** Create `parsers/registry.py` with `ParserAdapter.detect()` and `.parse()` abstractions; register PDF and HTML; provide factory `get_adapter(mime, source_type)`.
**Acceptance:** Unit tests select correct adapter for fixtures.

---

## 7) Derived Writer & DB Batcher
**Prompt:** Implement `workers/derived_writer.py` to stream chunks to `/derived/{doc_id}/chunks.jsonl` and bulk insert DB rows (batch=500); idempotent per `(doc_id, version)`.
**Acceptance:** Re-parse overwrites JSONL and replaces DB rows without duplication.

---

## 8) Bulk Metadata Apply
**Prompt:** `POST /bulk/metadata` that applies a JSON Patch to a selection (doc_id + chunk_id range or predicate). Write an `Audit` per chunk with correlation id.
**Acceptance:** Bulk apply updates targeted chunks atomically; audits written.

---

## 9) Audit Log API
**Prompt:** Implement `GET /audits?doc_id=&user=&action=&since=` returning paginated audit entries with server-side filtering and CSV export via `Accept: text/csv`.
**Acceptance:** Filters work; CSV export downloads with correct headers.

---

## 10) Correlation IDs
**Prompt:** Middleware to stamp `X-Request-ID` on inbound requests; propagate to Celery tasks and logs; include in audit entries.
**Acceptance:** Same id visible across API and worker logs for a given document.

---

## 11) RBAC (viewer/curator) per Project
**Prompt:** Add JWT-based auth with roles; protect edit endpoints; include a `@require_role('curator')` decorator.

**Acceptance:** Viewer gets 403 on edit; Curator can edit; unit tests cover role enforcement.

---

## 12) Signed URL Policy Enforcement
**Prompt:** Ensure all artifact routes return presigned URLs and never raw bucket paths. Add config for default expiry and a denylist of public ACLs.
**Acceptance:** Grep shows no public S3 URLs; presigned links expire correctly.

---

## 13) Golden Set Corpus & Demo Script
**Prompt:** Place small PDFs/HTML in `examples/golden/` with licenses; write `scripts/demo.sh` to ingest→parse→open LS project→export.
**Acceptance:** New devs can run end-to-end demo locally in <10 minutes.

---

## 14) CI Pipeline (lint/test/build)
**Prompt:** GitHub Actions workflow with jobs: lint, unit, e2e, build-and-push (on tags); cache Python deps; collect test artifacts.
**Acceptance:** PRs show green checks; artifacts downloadable from Actions.

---

## 15) Alembic models with chunk text hash & revisioning
**Prompt:** Create SQLAlchemy models and an Alembic migration for Project, Document, Chunk, Audit, Export, ExportManifest.
Add fields: `Chunk.text_hash (char(64))`, `Chunk.rev (int, default 1)`; unique index `(doc_id, order, rev)`; functional index on `text_hash`.
Add `Document.doc_hash` (sha256) and `Document.version`.
**Accept:** `alembic upgrade head` works; same `order`+higher `rev` allowed; text_hash computed in parser pipeline.

---

---

## 16) Forward-migration of metadata on re-parse
**Prompt:** Implement `migrate_metadata(old_chunks, new_chunks)` to carry `metadata` forward when `text_hash` matches; if text differs, bump `rev` and do not copy.
**Accept:** Test: edit metadata → re-parse same text preserves; changed text does not.

---

---

## 17) Taxonomy with labeling guidelines
**Prompt:** Extend taxonomy with `helptext` and `examples[]` per field; enforce `required` fields; surface in API and LS config generator.
**Accept:** Guidelines visible in LS UI; invalid values rejected (422).

---

---

## 18) Label Studio config generator + webhook
**Prompt:** Generate LS XML config to show chunk text and editors for taxonomy fields. Implement webhook `POST /webhooks/label-studio` to update `chunk.metadata` and append an `Audit`.
**Accept:** Posting sample LS payload updates metadata and creates audit row.

---

---

## 19) Universal Chunker (token/section aware) with stable ordering
**Prompt:** Implement `chunking/chunker.py` merging parser blocks into ~1000-token chunks; preserve `section_path`/`page`; compute `text_hash` on normalized text; never cross table placeholders.
**Accept:** Deterministic order & text_hash on fixtures.

---

---

## 20) PDF & HTML parsers v1
**Prompt:** `parsers/pdf.py` (PyMuPDF) and `parsers/html.py` (BeautifulSoup) → emit blocks with anchors → feed chunker. Persist to `/derived/{doc_id}/chunks.jsonl`; batch insert DB. Skip OCR/tables.
**Accept:** empty_chunk_ratio < 0.1 (PDF); section_path ≥ 90% (HTML).

---

---

## 21) Exports + RAG preset
**Prompt:** Jinja2-based exporters. Endpoints: `POST /export/jsonl` and `/export/csv` with filters+template id. Ship built-in RAG preset: `{ "context": "<section_path>: <text>", "answer": "" }`. Write `manifest.json` (doc_ids, taxonomy_version, parser_commit, template_hash).
**Accept:** Same inputs → byte-identical outputs; RAG preset works.

---

---

## 22) Rule-based suggestors + Accept flow
**Prompt:** `suggestors/rules.py` for severity, step id, ticket id, datetime; return value, confidence, rationale, span. `POST /chunks/{id}/accept-suggestion` (and bulk) to copy into metadata with audit.
**Accept:** Edge-case tests pass; metadata updated & audited.

---

---

## 23) Curation completeness metric & gates
**Prompt:** Compute completeness for required fields; add gates to set `needs_review` when below threshold or parse metrics exceed limits. Expose `/documents/{id}/metrics`.
**Accept:** API returns completeness; docs flip status as thresholds change.

---

---

## 24) Project settings (engine toggles & cost guards)
**Prompt:** Add `project_settings` with `use_rules_suggestor=true`, `use_mini_llm=false`, `max_suggestions_per_doc`, `suggestion_timeout_ms`. Wire into suggestor pipeline.
**Accept:** Changing settings alters suggestion behavior on next job.

---

---

## 25) Scorecard CLI + CI
**Prompt:** `scripts/scorecard.py` ingests golden set, runs parse, prints: chunks_per_doc, empty_ratio, section_path_coverage, curation_completeness. Add GitHub Actions workflow to enforce thresholds.
**Accept:** CI prints metrics and fails on breach.

---

---



## Deferred (Phase 1.5) stubs
**Prompt:** Create flagged stubs for Logs parser, Chat parser, Table extraction, OCR, Span/NER + spaCy export. Document as out-of-scope in README.
**Accept:** Flags and README entries exist; disabled by default.
