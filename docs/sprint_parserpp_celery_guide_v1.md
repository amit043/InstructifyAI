# Parser++ (Celery) Backlog Guide

## Overview
Parser++ extends the existing parsing pipeline with a multi-stage Celery orchestration focused on OCR-enhanced text extraction and improved metrics. Highlights:
- Celery-based task chaining for parsing stages
- OCR fallback for PDFs and HTML bundles
- Expanded metrics, structure inference, and chunking v2
- Manifest and observability upgrades

## Scope locks
- Celery-only orchestration (no Prefect/Airflow/Kubeflow).
- OCR text extraction only (no semantic layout reconstruction).
- No full table extraction in this phase (emit placeholders).
- Local/MinIO only; access via presigned URLs.
- Keep existing RBAC (viewer/curator).

## Golden path order
1. C10-00 deps → 2) C10-01 orchestrator → 3) C10-02 preflight/normalize
2. C10-03 PDF+OCR → 5) C10-04 UTF metrics → 6) C10-05 HTML ZIP
3. C10-06 HTML crawl → 8) C10-07 structure v2 → 9) C10-08 chunker v2
4. C10-09 manifest v2 → 11) C10-10 gates v2 → 12) C10-11 parser settings
5. C10-12 golden set & scorecard → 14) C10-13 observability & queues

## How to run locally
1. Start the stack: `make dev`
2. Ingest a document via the API (file upload or crawl)
3. Trigger re-parse as needed
4. Tail logs: `docker compose logs -f worker`
5. Derived artifacts: MinIO `s3://labeler-dev/derived/{doc_id}/`

## Task list
### C10-00 Worker deps & Docker base
- **Description:** Install tesseract-ocr, add Python deps (pymupdf, pytesseract, charset-normalizer, bs4, lxml, httpx). Build worker image with these layers.
- **Acceptance Criteria:** Worker container builds successfully; tesseract --version logs in startup; Python libs import without error.
- **DoD:** Dockerfile.worker updated; compose overrides ok; README notes Windows/WSL step.
- **Key Files:** docker/Dockerfile.worker; docker-compose.yml; README.md
- **Tests:** tests/test_worker_imports.py
- **PR name:** [C10-00] Worker deps (tesseract + libs)

### C10-01 Celery Canvas orchestrator skeleton
- **Description:** Introduce chain/group/chord flow: preflight → normalize → extract → (optional OCR fan-out) → structure → chunk+write → finalize.
- **Acceptance Criteria:** Calling orchestration schedules tasks; status transitions persisted; per-stage audits with request_id.
- **DoD:** Idempotent writes to /derived; small flow unit test with fakes.
- **Key Files:** worker/flow.py; worker/tasks/*.py; core/correlation.py
- **Tests:** tests/test_orchestrator_flow.py
- **PR name:** [C10-01] Celery Canvas orchestrator

### C10-02 Preflight & normalization
- **Description:** Detect mime/encoding; normalize to UTF-8, NFKC; strip control chars; standardize newlines; record metrics (control_char_count, non_utf8_ratio).
- **Acceptance Criteria:** Preflight+normalize returns payload+metrics; bad encodings handled; metrics written to DocumentVersion.meta.parse.
- **DoD:** parser_pipeline/preflight.py; parser_pipeline/normalize.py
- **Key Files:** parser_pipeline/preflight.py; parser_pipeline/normalize.py
- **Tests:** tests/test_preflight_normalize.py
- **PR name:** [C10-02] Preflight & normalization

### C10-03 PDF v2 with OCR fallback
- **Description:** PyMuPDF text per page; if text_len<50 & images>0 → OCR via pytesseract (DPI 300, lang from project settings). Merge text; keep ocr_conf_mean.
- **Acceptance Criteria:** Text-only PDFs skip OCR; scanned pages gain text; per-page metrics stored; blocks include page + source_stage.
- **DoD:** parsers/pdf_v2.py
- **Key Files:** parsers/pdf_v2.py
- **Tests:** tests/test_pdf_v2_ocr.py
- **PR name:** [C10-03] PDF extractor v2 + OCR

### C10-04 UTF/char coverage metrics
- **Description:** Compute ascii/latin1/other ratios & invalids removed; store before/after extraction.
- **Acceptance Criteria:** Ratios visible in DocumentVersion.meta.parse; unit tests cover edge unicode.
- **DoD:** parser_pipeline/metrics.py
- **Key Files:** parser_pipeline/metrics.py
- **Tests:** tests/test_char_coverage.py
- **PR name:** [C10-04] UTF coverage metrics

### C10-05 HTML bundle (ZIP) ingest + parse
- **Description:** POST /ingest/zip stores bundle.zip; worker unzips temp, traverses *.html; parse each via BeautifulSoup; emit blocks with file_path.
- **Acceptance Criteria:** Chunks/JSONL include file_path; manifest lists files; MinIO derived present.
- **DoD:** api/main.py; parsers/html_bundle.py; storage/object_store.py
- **Key Files:** api/main.py; parsers/html_bundle.py; storage/object_store.py
- **Tests:** tests/test_ingest_zip_bundle.py
- **PR name:** [C10-05] HTML ZIP ingest + parse

### C10-06 HTML crawl ingest (URI set)
- **Description:** POST /ingest/crawl {base_url, allow_prefix, max_depth, max_pages}; httpx fetch; same-host, prefix-constrained; store crawl_index.json; parse pages.
- **Acceptance Criteria:** Multi-page doc created; chunks include file_path+url; rate limiting & dedupe handled.
- **DoD:** api/main.py; parsers/html_crawl.py
- **Key Files:** api/main.py; parsers/html_crawl.py
- **Tests:** tests/test_ingest_crawl.py
- **PR name:** [C10-06] HTML crawl ingest + parse

### C10-07 Structure inference v2
- **Description:** Titles: font-size heuristic (PDF), h1..h6 (HTML); tables → table_placeholder; build section_path.
- **Acceptance Criteria:** Blocks carry kind, section_path; table placeholders present where expected.
- **DoD:** parser_pipeline/structure.py
- **Key Files:** parser_pipeline/structure.py
- **Tests:** tests/test_structure_infer.py
- **PR name:** [C10-07] Structure inference v2

### C10-08 Chunker v2 (multi-file aware)
- **Description:** Respect file_path & title boundaries; ~900-token max; deterministic splits.
- **Acceptance Criteria:** Chunk meta contains file_path,page,section_path; golden determinism test.
- **DoD:** chunking/chunker_v2.py
- **Key Files:** chunking/chunker_v2.py
- **Tests:** tests/test_chunker_v2.py
- **PR name:** [C10-08] Chunker v2

### C10-09 Derived writer + manifest v2
- **Description:** Write chunks.jsonl and manifest.json: tool_versions, thresholds, stage_metrics, files, pages_ocr; presign URLs.
- **Acceptance Criteria:** Manifest present with expected fields; presigned URLs returned; lineage reproducible.
- **DoD:** worker/derived_writer.py; storage/object_store.py
- **Key Files:** worker/derived_writer.py; storage/object_store.py
- **Tests:** tests/test_manifest_v2.py
- **PR name:** [C10-09] Manifest & lineage

### C10-10 Metrics & quality gates update
- **Description:** Add text_coverage, ocr_ratio, utf_other_ratio; mark needs_review if thresholds breached; surface in /documents.
- **Acceptance Criteria:** Toggling thresholds changes result; tests for pass/fail.
- **DoD:** core/metrics.py; worker/main.py; api/main.py
- **Key Files:** core/metrics.py; worker/main.py; api/main.py
- **Tests:** tests/test_quality_gates_v2.py
- **PR name:** [C10-10] Metrics + gates v2

### C10-11 Project settings for parser thresholds/lang
- **Description:** Extend project settings: ocr_langs, min_text_len_for_ocr, html_crawl_limits. Worker reads on each task.
- **Acceptance Criteria:** PATCH /projects/{id}/settings updates behavior without redeploy.
- **DoD:** api/schemas.py; api/main.py; core/settings.py; worker/pipeline.py
- **Key Files:** api/schemas.py; api/main.py; core/settings.py; worker/pipeline.py
- **Tests:** tests/test_parser_settings.py
- **PR name:** [C10-11] Parser settings wiring

### C10-12 E2E golden set & scorecard update
- **Description:** Add example ZIP & mixed PDF; scorecard validates gates; make target runs end-to-end.
- **Acceptance Criteria:** make scorecard passes on golden; CI smoke added.
- **DoD:** examples/bundles/*; scripts/scorecard.py; Makefile
- **Key Files:** examples/bundles/*; scripts/scorecard.py; Makefile
- **Tests:** tests/test_scorecard_e2e.py
- **PR name:** [C10-12] Golden set + scorecard

### C10-13 Observability & backpressure
- **Description:** Per-stage audits, request_id propagation; Celery routing (q=ocr) & concurrency caps; doc status per stage.
- **Acceptance Criteria:** Logs show request_id; audits written; OCR queue capped via compose.
- **DoD:** core/correlation.py; worker/celery_app.py; docker-compose.yml
- **Key Files:** core/correlation.py; worker/celery_app.py; docker-compose.yml
- **Tests:** tests/test_request_id_and_routing.py
- **PR name:** [C10-13] Observability + queues

## Per-task prompt template
```
Read /docs/sprint_parserpp_celery_tasks_v1.csv and open the row {TASK_ID}.
Restate AcceptanceCriteria and DoD, propose a brief design, then implement: code, tests, minimal docs.
Keep diffs minimal; follow existing project patterns.
Run `make lint test`; update STATUS.md.
Open PR titled as in the CSV “PR” column, branch feature/{TASK_ID}-short-name.
Start with {TASK_ID} now.
```
