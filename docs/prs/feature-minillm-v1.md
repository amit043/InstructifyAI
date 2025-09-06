Title: Mini‑LLM v1 toggles, v2 parser tunables, and training scaffolding

Summary
- Adds project‑level engine toggles incl. `use_mini_llm` (default false) alongside existing rules suggestor flags.
- Introduces parser v2 tunables on `projects`: `download_images`, `max_image_bytes`, `chunk_token_target`, `chunk_token_overlap`.
- Wires tunables through API (`/projects/{id}/settings`) and worker v2 pipeline settings pass‑through.
- Provides training scaffolding (SFT/MFT/ORPO) with PEFT strategies (LoRA/QLoRA/DoRA) and optional RWKV/HF backends; tests are skip‑guarded when heavy deps are missing.
- Alembic migration 0014 adds new columns; backwards‑compatible defaults.

Backlog IDs
- E9‑03: Project settings wiring (engine toggles & cost guards)
- C10‑14: Parser pipeline v2 router (non‑breaking)
- C10‑11: Parser settings wiring (extended)

Acceptance Criteria
- Toggling settings affects behavior without redeploy: worker/exporters respect `use_rules_suggestor`/`use_mini_llm`.
- New parser v2 tunables are returned from and persisted by project settings endpoints.
- Alembic `upgrade head` and `downgrade base` succeed.

Key Changes
- DB: `alembic/versions/0014_add_v2_tunables.py` adds 4 columns on `projects` with sane defaults.
- Model: `models/project.py` exposes new fields with defaults and server defaults.
- API: `GET/PATCH /projects/{id}/settings` now includes the new fields (see `api/schemas.py`, `api/main.py`).
- Worker v2: `worker/pdf_v2.py`, `worker/html_v2.py`, and `worker/pipeline/__init__.py` consume tunables for chunk sizing and image handling.
- Tests: settings toggles and v2 router behavior covered; OCR‑related tests skip if Tesseract missing.

How to Validate Locally
- make migrate
- make lint
- make test (subset; or run pytest for broader coverage)
- Smoke: ingest small HTML/PDF, parse via `worker.main.parse_document(doc_id, version, pipeline="v2")` and inspect derived `chunks.jsonl` sizing.

Security / Scope
- Phase‑1 locks respected: mini‑LLM is disabled by default and gated; OCR/table behavior is unchanged except optional v2 image OCR paths already guarded and skip‑friendly.
- No public bucket paths; signed URLs enforced as before.

Notes
- No breaking API changes; defaults maintain current behavior on existing projects.

