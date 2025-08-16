
# Sprint-2 Backlog — Curation → Export (Phase-1 finish)

**Source files for agents**
- CSV backlog: `/docs/sprint2_tasks_v1.csv`
- This guide: `/docs/sprint2_agents_guide_v1.md`

**Scope locks (do not drift):**
- LS-first UI; no custom React in Phase-1
- No spans/NER, no OCR; tables → placeholders
- Local upload + S3/MinIO only
- Presigned URLs only; RBAC (viewer/curator)

---

## Golden Path
1. E4-01…E4-05 — taxonomy → LS config → webhook → bulk apply
2. E5-01…E5-03 — templates → exporters(+manifest) → RAG preset
3. E6-01…E6-04 — suggestors → accept → completeness → gates
4. E7-01…E7-03 — correlation IDs → audit API → scorecard
5. E9-01…E9-03 — JWT RBAC → signed URLs only → project settings
6. F1-01, F2-01 — CI + Postman & README

---

## Working Instructions for Codex
1. **Read**: `/AGENTS.md`, `/docs/phase1_backlog_tasks_v2.csv`, `/docs/codex_prompt_pack_phase1_v2_1_merged.md`, and `/docs/sprint2_tasks_v1.csv`.
2. **For each row in `/docs/sprint2_tasks_v1.csv`**:
   - Restate **Acceptance Criteria**
   - Propose brief design choices
   - Implement code + tests
   - Run `make lint test` (simulate if needed)
   - Update `STATUS.md`
   - Open PR named as in the **PR** column (one task per PR)
3. **Honor scope locks** above and the Definition of Done in the CSV.

---

## Kickoff Prompt (copy-paste into Codex)
Re-read `/AGENTS.md`, `/docs/codex_prompt_pack_phase1_v2_1_merged.md`, and `/docs/sprint2_tasks_v1.csv`.
Start with **E4-01** and proceed in order. For each task, restate AC, implement with tests, update `STATUS.md`, and open a PR titled per the CSV. Keep changes minimal and incremental. **Do not drift Phase-1 scope.**

---

## Definition of Done (Sprint-2)
- AC satisfied (tests/docs)
- Contracts updated (Pydantic/Alembic/OpenAPI)
- Lint/type/tests green locally + CI
- No scope drift; security (RBAC, presigned URLs) enforced
- `STATUS.md` updated; Postman examples added where relevant
