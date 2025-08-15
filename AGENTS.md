
# AGENTS.md — Build Guide for Codex & Contributors (Phase‑1, scope‑locked)

**Project:** AI Labeler for Unstructured Data (Phase‑1 “Dataset Factory”)  
**Audience:** Autonomous coding agents (Codex) and human contributors with senior Backend/AI/Data Eng experience.  
**Mission:** Ship a *walking skeleton* that ingests PDFs/HTML → parses to a **canonical chunk format** → enables **human metadata curation** (Label Studio, LS-first) → **exports** JSONL/CSV (incl. RAG preset) with **reproducible manifests**.

---

## 0) Non‑negotiable Scope Locks (Phase‑1 MVP)
- **LS‑first UI**: Use **Label Studio** for annotation/curation. No custom React in Phase‑1.
- **No spans/NER** in Phase‑1 (defer to 1.5). Only **document/chunk metadata & classification**.
- **Tables**: robust extraction deferred to 1.5. Emit **table placeholders** only.
- **OCR**: deferred to 1.5 (no Tesseract in Phase‑1).
- **Connectors**: **Local upload + S3/MinIO only** (no SharePoint/Confluence/etc.).
- **Privacy**: PII detection = **preview-only**, no destructive writes. Redaction at export (1.5).

> If a requirement conflicts with these locks, prefer **shipping the walking skeleton** over expanding scope.

---

## 1) Execution Contract for Agents (how to work)
1. **Load the spec files**: 
   - `/docs/phase1_backlog_tasks_v2.csv` (Backlog v2, scope‑locked)
   - `/docs/codex_prompt_pack_phase1_v2_1_merged.md` (Prompt pack v2.1)
2. **Work task‑by‑task** in this order for MVP:
   - `E1-01`→`E1-04`, `E2-01`→`E2-04`, `E3-02`→`E3-05`, `E3-03`/`E3-04`, `E4-01`→`E4-05`, `E5-01`→`E5-03`, `E6-01`→`E6-04`, `E7-01`→`E7-03`, `E8-01`→`E8-03`, `E9-01`→`E9-03`.
3. **For each task**:
   - Restate **Acceptance Criteria** (AC) from backlog.
   - Propose design decisions if needed (default to listed tech).
   - Generate code + tests. **Do not** bypass AC.
   - Run linters/tests locally (or simulate where runtime is unavailable).
   - Output **diffs** and a **STATUS.md** update.
4. **Only merge when DoD passes** (see §11) and all checks are green.
5. **Never drift scope**. If blocked by credentials or external services, **stub with fakes** and proceed.

---

## 2) Golden Path (Walking Skeleton)
1. **Infra**: docker‑compose (api/worker/postgres/redis/minio), pydantic‑settings, Alembic baseline.
2. **Ingestion**: `/ingest` (file/URI) → object store (MinIO/S3) + **doc_hash** dedup; document registry + listing.
3. **Parsing**: ParserRegistry + **Universal Chunker** (token & section aware); adapters: **PDF (PyMuPDF), HTML (BS4)**.
4. **Derived artifacts**: stream `/derived/{doc_id}/chunks.jsonl`, batch insert chunks DB; idempotent re‑parse.
5. **Curation**: Versioned **taxonomy** w/ **helptext+examples**; **LS project config** generator; **webhook** to patch chunk metadata; **bulk apply**.
6. **Exports**: Jinja2 templates for JSONL/CSV + **manifest**; **RAG preset** (`context`,`answer`).
7. **Suggestions**: **Rule‑based** (severity, step id, ticket id, datetime) + **Accept Suggestion** flow.
8. **Quality**: metrics, **curation completeness** (% required fields set), quality gates (`needs_review`).
9. **Ops**: correlation IDs, audit API, scorecard CLI, CI, RBAC, signed URLs, project settings (engine toggles).

---

## 3) System Outline
```
api/ (FastAPI)         workers/ (Celery)         storage/           exporters/
  routes/                tasks/                    object_store.py     jsonl.py
  schemas/               parsers/ (pdf, html)      db.py               csv.py
  services/              chunking/ (chunker.py)    models/ (ORM)       templates/
  main.py                suggestors/               migrations/       label_studio/
                                                               scripts/ examples/golden/
```

**Tech**: Python 3.11+, FastAPI, SQLAlchemy, Alembic, Celery+Redis, Postgres, MinIO (S3 API), PyMuPDF, BeautifulSoup4, Jinja2.  
**Style**: type‑hints, mypy, black, isort, pytest.

---

## 4) Runbook

### 4.1 Toolchain
- Python 3.11+, Docker + docker‑compose, `make`, `uv` or `poetry`.
- Optional: `just`, `pre‑commit`.

### 4.2 Makefile Targets (required)
```
make setup       # install deps, pre-commit
make dev         # run api + worker + deps via docker-compose
make lint        # black, isort, mypy
make test        # unit and e2e (golden set)
make migrate     # alembic upgrade head
make demo        # run examples/golden end-to-end
```

### 4.3 .env.example (Phase‑1)
```
ENV=DEV
POSTGRES_HOST=postgres
POSTGRES_DB=labeler
POSTGRES_USER=labeler
POSTGRES_PASSWORD=labeler
POSTGRES_PORT=5432
DATABASE_URL=postgresql+psycopg2://labeler:labeler@postgres:5432/labeler

REDIS_URL=redis://redis:6379/0

MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_SECURE=false
S3_BUCKET=labeler-dev

JWT_SECRET=change-me
EXPORT_SIGNED_URL_EXPIRY_SECONDS=600
SUGGESTION_TIMEOUT_MS=500
MAX_SUGGESTIONS_PER_DOC=200
ALLOW_VERSIONING=false
```

### 4.4 Docker Compose (summary)
- Services: `api`, `worker`, `postgres`, `redis`, `minio`, `minio-console`.
- Healthchecks; mounted volumes for dev; shared network.
- `api` exposes `:8000` with `/health` and `/metrics` (Prometheus‑ready).

---

## 5) Data Contracts (authoritative)

### 5.1 Document (DB)
- `doc_id (uuid)`, `project_id`, `source_type (pdf|html)`, `mime`, `doc_hash (sha256)`, `size`, `status (ingested|parsed|needs_review|failed)`, `version (int)`, `metadata JSONB`, timestamps.

### 5.2 Chunk (DB + JSONL line)
```json
{
  "doc_id":"UUID","chunk_id":"UUID","order":27,"rev":1,
  "source":{"type":"pdf","page":5,"section_path":["Intro","Method"],"line_range":[120,156]},
  "content":{"type":"text","text":"..."},
  "text_hash":"<sha256-of-normalized-text>",
  "metadata":{"severity":"INFO","doc_tags":["SOP"]},
  "suggestions":{"severity":{"value":"INFO","confidence":0.92,"rationale":"regex: 'INFO'","span":[0,4]}},
  "audit":{"created_by":"system","created_at":"..."}
}
```
**Rules**
- `order` stable; `rev` bumps when text changes (no implicit label carry).
- Forward‑migrate metadata when `text_hash` unchanged.

### 5.3 Taxonomy (per project, versioned)
- Fields: `name`, `type (string|enum|bool|number|date)`, `required`, `helptext`, `examples[]`, `enum_values?`.

### 5.4 Export Manifest
```json
{
  "export_id":"...","doc_ids":["..."],"taxonomy_version":3,
  "parser_commit":"<git>", "suggestors_commit":"<git>", "ucdm_schema_ver":"1",
  "template_hash":"...", "created_at":"...", "filters":{"project_id":"..."}
}
```

---

## 6) API Checklist (Phase‑1)
- `POST /ingest` (multipart or `{uri}`) → `{doc_id}`
- `GET /documents` (filters: project_id, type, status, q, page, limit)
- `GET /documents/{doc_id}` (status, counts, metrics)
- `POST /documents/{doc_id}/parse` (re‑run)
- `GET /documents/{doc_id}/chunks?offset=&limit=&q=`
- `PATCH /chunks/{chunk_id}/metadata`
- `POST /bulk/metadata` (range/filter)
- `GET/PUT /projects/{id}/taxonomy` (+ guidelines)
- `POST /label-studio/config` (render LS XML from taxonomy)
- `POST /webhooks/label-studio` (apply edits → audit)
- `POST /export/jsonl|csv` (template or preset) → signed URL
- `GET /audits?doc_id=&user=&action=&since=` (+ CSV via `Accept: text/csv`)
- `GET /documents/{id}/metrics` (parse & curation completeness)
- `GET /metrics` (Prometheus) — optional P1
- **Auth/RBAC**: JWT; viewer vs curator per project

---

## 7) Universal Chunker & Parsers (key behaviors)
- **Chunker targets ~700–1000 tokens**; respect headings/paragraphs; never cross `content.type="table_placeholder"` boundaries.
- **Anchors**: include `page`, `section_path`, `line_range|xpath` when available.
- **Determinism**: ordering stable across runs.
- **Parsers**:
  - **PDF (PyMuPDF)**: text blocks, page anchors, basic heading heuristic; OCR **off**.
  - **HTML (BS4)**: strip boilerplate (nav/footer/aside), compute `section_path` from `h1..h6`, preserve `<pre><code>` as code, emit table placeholders.

---

## 8) Label Studio Integration
- **Config generator** takes active taxonomy → LS XML with field widgets + **helptext**.
- **Webhook** validates payload, patches `chunk.metadata`, writes **Audit** (`who, when, what, old→new`).
- **Bulk apply** supports range / predicate selection; atomic; one audit per chunk.
- **RBAC**: only **Curator** can edit; **Viewer** gets 403.

---

## 9) Suggestions (Rules‑only, Phase‑1)
Detectors:
- **Severity**: `(DEBUG|INFO|WARN|ERROR|FATAL)`
- **Step id**: `^Step\s?\d+:`
- **Ticket id**: `(JIRA|BUG|INC)-\d+`
- **Datetime**: common ISO‑8601/date patterns
Return `{field, value, confidence, rationale, span}` into `suggestions.*`.
**Accept Suggestion** endpoint copies value → `metadata` and writes an audit. No auto‑writes.

---

## 10) Exports & Presets
- **Template DSL (Jinja2)** maps `instruction|input|output|label|meta` from `chunk/doc`.
- **RAG preset**:
```json
{"context": "{{ ' / '.join(chunk.source.section_path) }}: {{ chunk.content.text }}",
 "answer": ""}
```
- Exports materialize under `/exports/{export_id}/…` with **manifest.json**.
- **Idempotent**: identical filters + template hash → same export (reuse).

---

## 11) Quality, Metrics & Gates
- **Parse metrics**: `chunks_total`, `empty_chunk_ratio`, `parse_error_ratio`.
- **Curation**: **completeness** = % chunks meeting `required` taxonomy fields.
- **Gates** (defaults, tune per project):
  - `empty_chunk_ratio <= 0.10`
  - `section_path_coverage (HTML) >= 0.90`
  - `curation_completeness >= 0.80`
- **Statuses**: set `needs_review` if any gate fails; surface in UI/API.
- **Scorecard CLI**: runs on **Golden Set** and enforces thresholds.

---

## 12) Observability & Security
- **Correlation IDs**: stamp `X‑Request‑ID`, propagate to Celery & audits.
- **Logging**: JSON logs with `level, ts, request_id, doc_id, event`.
- **Metrics**: Prometheus (optional P1) `ingest_total, parse_duration_seconds, chunks_per_doc, suggestion_accept_rate`.
- **Security**: Access raw/derived/exports only via **time‑limited signed URLs**; **never** public bucket paths.
- **RBAC**: JWT auth; **Viewer** vs **Curator**.
- **PII**: preview‑only flags in `suggestions.redactions` (no write).

---

## 13) Coding Standards & Tenets
- **Determinism > cleverness** (stable ordering, idempotent writes).
- **Contracts first**: Pydantic schemas, Alembic migrations, OpenAPI.
- **Fail fast**: clear 4xx for validation errors (taxonomy, webhook).
- **Small batches**: chunk DB bulk‑insert; streaming JSONL writes.
- **Test the edges**: malformed PDFs, huge HTML, empty pages.

---

## 14) Branching & PR Policy
- Branch per backlog ID (e.g., `feature/E3-02-chunker`).
- PR must include: description, linked task IDs, tests, screenshots (if relevant), **STATUS.md** update.
- Block merge until: all AC met, lint/test green, reviewer sign‑off.

---

## 15) Definition of Done (checklist)
- [ ] AC satisfied (link task IDs)
- [ ] Contracts updated (Pydantic/Alembic/OpenAPI)
- [ ] Lint/type/test pass locally + CI
- [ ] Docs updated (`README.md`, `STATUS.md`)
- [ ] No scope drift (Phase‑1 locks honored)
- [ ] Security checks: signed URLs only, RBAC enforced

---

## 16) Common Pitfalls (avoid)
- Parsing tables aggressively (deferred) → **emit placeholders**.
- Span/NER labels (deferred) → avoid adding span editors/export now.
- OCR (deferred) → do not add Tesseract.
- Implicit metadata writes from suggestions → **must be curator‑approved**.
- Losing labels on re‑parse → rely on `text_hash` + `rev` migration.

---

## 17) Kickoff Script for Agents (copy‑paste)
> Use the repo files `/docs/phase1_backlog_tasks_v2.csv` and `/docs/codex_prompt_pack_phase1_v2_1_merged.md`.  
> Start with E1‑01..E1‑04, E2‑01..E2‑04. For each task: restate AC, propose design, implement, add tests, run `make lint test migrate`, show diffs, update STATUS.md.  
> Maintain scope locks (LS‑first; no spans/NER; tables & OCR deferred; Local/S3 only).  
> If external creds missing, stub/fake and continue. Do not skip acceptance gates.

---

## 18) Appendix — Golden Set Expectations
- Include **5 PDFs** (≥250 pages), **5 HTML reports**; plus small logs/chat placeholders for future.
- Expected metrics on scorecard: `empty_chunk_ratio <= 0.10`, `section_path_coverage >= 0.90`.
- Demo target: ingest→parse→LS tag (1–2 fields)→export JSONL/CSV within **10 minutes** locally.

---

**End of AGENTS.md** — stay lean, ship the skeleton, then iterate.
