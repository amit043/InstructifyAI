
# STATUS.md — Phase‑1 (Dataset Factory) — Project Health

> Keep this file up to date. One section per sprint, one row per shipped task.
> Source of truth for scope locks, risks, gates, and demo readiness.

---

## 0) Snapshot (fill weekly)
- **Week of:** 2025-08-15
- **Overall status:** ☐ Green ☐ Yellow ☐ Red
- **MVP ETA:** <date>
- **Demo ready?** ☐ Yes ☐ No (why?)
- **Owners:** PM <name> · Tech Lead <name> · Backend <name> · Data/AI <name>

**Scope locks (must stay true)**
- LS‑first curation UI (Label Studio); no custom React in Phase‑1.
- No spans/NER; no OCR; robust tables deferred to 1.5 (placeholders only).
- Connectors: Local upload + S3/MinIO only.
- PII: preview‑only; no destructive writes.
- Reproducible exports + manifest; idempotent re‑parse.

---

## 1) Milestones & Gates
| Milestone | Definition of Done | Status |
|---|---|---|
| Walking skeleton | ingest→parse→LS tag→export works on golden set | ☐ |
| Quality gates set | parse metrics + curation completeness enforced | ☐ |
| RAG preset export | context+answer JSONL available | ☑ |
| Audit + RBAC | viewer/curator enforced; audit API live | ☑ |
| CI green | lint/test/scorecard green on main | ☑ |

**Quality thresholds (can tune per project)**
- `empty_chunk_ratio ≤ 0.10`
- `section_path_coverage (HTML) ≥ 0.90`
- `curation_completeness ≥ 0.80`

---

## 2) Task Progress (link to PRs)
> Source: `/docs/phase1_backlog_tasks_v2.csv`. Keep high‑signal rows here.

| ID | Title | Owner | Status | PR | Notes |
|---|---|---|---|---|---|
| E1‑01 | Bootstrap repo & toolchain | codex | ☑ Done | PR TBD |  |
| E1-02 | Docker Compose stack | codex | ☑ Done | PR TBD |  |
| E1-03 | Pydantic settings & config profiles | codex | ☑ Done | PR TBD |  |
| E1-04 | Alembic baseline | codex | ☑ Done | PR TBD |  |
| E3‑02 | Universal Chunker | codex | ☑ Done | PR TBD |  |
| E2-01 | Object store client | codex | ☑ Done | PR TBD |  |
| E2-02 | Document registry schema | codex | ☑ Done | PR TBD |  |
| E2-03 | /ingest endpoint | codex | ☑ Done | PR TBD |  |
| E2-04 | Document list & filters | codex | ☑ Done | PR TBD |  |
| E2-05 | Document detail & chunks retrieval | codex | ☑ Done | PR TBD |  |
| E3‑03 | PDF parser v1 | codex | ☑ Done | PR TBD |  |
| E3‑04 | HTML parser v1 | codex | ☑ Done | PR TBD |  |
| E3‑05 | Derived writer & DB batcher | codex | ☑ Done | PR TBD |  |
| E4‑01 | Taxonomy service v1 | codex | ☑ Done | [PR](#) |  |
| E4‑02 | Guidelines endpoint | codex | ☑ Done | [PR](#) |  |
| E4‑03 | LS project config | codex | ☑ Done | [PR](#) |  |
| E4‑04 | LS webhook → metadata | codex | ☑ Done | [PR](#) |  |
| E5‑01 | Template DSL (Jinja2) | codex | ☑ Done | [PR](#) |  |
| E5‑02 | JSONL/CSV exporters + manifest | codex | ☑ Done | [PR](#) |  |
| E5‑03 | RAG preset templates | codex | ☑ Done | [PR](#) |  |
| E6‑01 | Rule‑based suggestors v1 | codex | ☑ Done | [PR](#) |  |
| E6‑02 | Accept suggestion | codex | ☑ Done | [PR](#) |  |
| E6‑03 | Curation completeness metric | codex | ☑ Done | [PR](#) |  |
| E7‑02 | Audit retrieval API | codex | ☑ Done | PR TBD |  |
| E7‑03 | Scorecard CLI | codex | ☑ Done | PR TBD |  |
| E4‑05 | Bulk metadata apply | codex | ☑ Done | [PR](#) |  |
| E9‑01 | RBAC (viewer/curator) | codex | ☑ Done | PR TBD |  |
| E9‑02 | Project settings: engine toggles & cost guards | codex | ☑ Done | PR TBD |  |
| E9‑03 | Signed URL policy | codex | ☑ Done | PR TBD |  |
| E9-04 | Project onboarding API | codex | ☑ Done | PR TBD |  |
| E3-06 | Worker parse pipeline & error handling | codex | ☑ Done | PR TBD |  |

---

## 3) Metrics (from Scorecard / /metrics)
> Update after each CI run or demo.

| Metric | Value | Target | Pass? |
|---|---|---|---|
| empty_chunk_ratio (PDF) |  | ≤ 0.10 | ☐ |
| section_path_coverage (HTML) |  | ≥ 0.90 | ☐ |
| curation_completeness |  | ≥ 0.80 | ☐ |
| parse_duration_p95 (50‑page PDF) |  | < 30s | ☐ |

---

## 4) Risks & Mitigations
| Risk | Severity | Owner | Mitigation | Status |
|---|---|---|---|---|
|  | Low/Med/High |  |  | Open/Tracking/Closed |

---

## 5) Decisions Log (ADR‑lite)
| Date | Decision | Context | Owner |
|---|---|---|---|
|  |  |  |  |

---

## 6) DOR/DoD (check each PR)
**Definition of Ready (DOR)**  
- [ ] Task linked to backlog ID and acceptance criteria clear.  
- [ ] Contracts identified (schemas/migrations/OpenAPI).  
- [ ] Test strategy written.

**Definition of Done (DoD)**  
- [ ] AC satisfied (tests/docs).  
- [ ] Lint/type/test/scorecard green.  
- [ ] No scope drift vs Phase‑1 locks.  
- [ ] Security checks (RBAC, signed URLs) verified.  
- [ ] STATUS.md updated.

---

## 7) Demo Notes
- Command used: `make demo`
- Dataset: examples/golden
- What we showed: ingest→parse→curate→export
- Follow‑ups:
