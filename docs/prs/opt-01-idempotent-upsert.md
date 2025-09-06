Title: OPT-01 — Idempotent chunk upsert & core DB indexes

Summary
- Implement deterministic chunk IDs and idempotent batch insert with safe transactions.
- Add core indexes to improve document listing and JSONB metadata queries.

Scope
- Replace upsert logic in `worker/derived_writer.py::upsert_chunks` with:
  - Deterministic UUID: `uuid5(NAMESPACE_URL, f"{doc_id}|{version}|{order}|{text_hash}")`.
  - De-duplicate by id (last wins), delete missing rows, then insert in batches of 2000.
  - Wrap DB writes in try/except; rollback on error; single commit on success.
  - Artifact writers (`write_chunks`, `write_manifest`) unchanged.
- Add Alembic migration `0016_add_core_indexes`:
  - btree on `chunks(document_id, version, "order")` → `ix_chunks_doc_ver_order`.
  - btree on `documents(project_id)` → `ix_documents_project_id`.
  - gin on `chunks(metadata)` → `ix_chunks_metadata_gin`.

Acceptance
- Re-ingesting the same PDF twice does not error (idempotent insert, delete-then-insert avoids duplicate-key and ON CONFLICT UPDATE hazards).
- Query speed improved for project-scoped listings via new indexes.

How to run
1) Start dev stack and migrate:
   - `docker compose up -d`
   - `docker compose exec api alembic upgrade head`
2) Re-parse a document twice (same doc_id/version) and verify no errors.
3) Verify index presence:
   - `\d+ chunks` → check `ix_chunks_doc_ver_order`, `ix_chunks_metadata_gin`.
   - `\d+ documents` → check `ix_documents_project_id`.

Notes
- Deterministic IDs change when `text_hash` changes; old rows are removed for the same (doc_id, version) and replaced by new ids. This avoids the Postgres “ON CONFLICT DO UPDATE … affects row a second time” error mode under overlapping unique constraints.

