# InstructifyAI

[![CI](https://github.com/InstructifyAI/InstructifyAI/actions/workflows/ci.yml/badge.svg)](https://github.com/InstructifyAI/InstructifyAI/actions/workflows/ci.yml)

## Curation API

Phase‑1 exposes endpoints for managing a per‑project taxonomy and for applying
curation metadata to chunks. Endpoints require an `X-Role` header; only
`curator` may modify data while `viewer` can read.

* `POST /projects` – create a new project and return its `id`.
* `POST /projects/{project_id}/taxonomy` – create a new taxonomy version with
  field definitions including `helptext` and `examples`.
* `GET /projects/{project_id}/ls-config` – render a Label Studio configuration
  from the active taxonomy.
* `POST /webhooks/label-studio` – apply a metadata patch from a Label Studio
  webhook and append an audit entry.
* `POST /chunks/bulk-apply` – apply a metadata patch to many chunks at once,
  writing an audit row per chunk.
* `POST /chunks/{chunk_id}/suggestions/{field}/accept` – accept a rule-based
  suggestion for a single chunk.
* `POST /chunks/accept-suggestions` – accept a suggestion across many chunks.
* `GET /documents/{doc_id}/metrics` – return curation completeness metrics.
* `GET /audits?doc_id=&user=&action=&since=` – list audit entries (JSON or CSV via `Accept: text/csv`).

Each request is stamped with an `X-Request-ID` correlation identifier that
propagates to Celery tasks and audit rows.

Run `make scorecard` to execute the scorecard CLI on the golden set and enforce
curation completeness thresholds.

Audits are stored in the `audits` table with before/after values for each
change.
