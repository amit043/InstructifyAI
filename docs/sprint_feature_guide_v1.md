# Feature Backlog — Parser/Data Quality, Curation, Dataset Ops (v1)

## Overview
This sprint focuses on high-impact **features** (not security): better structure (tables, figures), smarter chunking, lightweight curation UX, and dataset governance (releases). Targets: higher dataset utility with lower curation effort and reproducible exports.

## Scope locks
- Keep current stack: FastAPI + Celery + Postgres + Redis + MinIO.
- Prefer additive metadata/schema changes over heavy migrations.
- Idempotent derived writes and deterministic exports.
- Label Studio remains supported; Curation Lite is metadata-only.

## Priorities (Now → Next → Later)
**Now:** F40-01, F40-02, F40-03, F40-04, F40-05  
**Next:** F40-06, F40-07, F40-08, F40-09  
**Later:** F40-10, F40-11, F40-12, F40-13, F40-14, F40-15

## Golden path (recommended order)
1) Tables v1.5 → 2) Figures+captions → 3) Layout-aware chunking → 4) Curation Lite UI → 5) Releases & snapshotting → 6) Active-learning → 7) Stratified splits → 8) Near-duplicate filtering → 9) Embeddings search → 10) Math/Code spans → 11) Multilingual OCR → 12) RAG eval → 13) CLI → 14) Notifications → 15) Guideline assistant

## How to run locally
- `make dev` (compose up API, worker, Postgres, Redis, MinIO)
- Ingest PDFs/HTML bundles; watch worker logs
- Derived artifacts at `s3://{bucket}/derived/{doc_id}/*` (via MinIO)
- For Curation Lite (when added): `http://localhost:8000/curation` (dev only)

## Task list
The CSV (`docs/sprint_feature_backlog_v1.csv`) contains full task specs with AcceptanceCriteria and DoD. Implement one task per PR.

## Per-task prompt template (for Codex)
```
Read /docs/sprint_feature_backlog_v1.csv and open row {TASK_ID}.
Restate AcceptanceCriteria and DoD. Propose a short design, then implement:
- Code in the indicated files (create modules if missing)
- Tests in the indicated path
- Minimal docs; update STATUS.md
Run `make lint test`; ensure green.
Open a PR titled as in the CSV “PR” column, branch `feature/{TASK_ID}-short-name`.
Start with {TASK_ID} now.
```
