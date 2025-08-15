# InstructifyAI

## Curation API

Phase‑1 exposes endpoints for managing a per‑project taxonomy and for applying
curation metadata to chunks. Endpoints require an `X-Role` header; only
`curator` may modify data while `viewer` can read.

* `POST /projects/{project_id}/taxonomy` – create a new taxonomy version with
  field definitions including `helptext` and `examples`.
* `GET /projects/{project_id}/ls-config` – render a Label Studio configuration
  from the active taxonomy.
* `POST /webhooks/label-studio` – apply a metadata patch from a Label Studio
  webhook and append an audit entry.
* `POST /chunks/bulk-apply` – apply a metadata patch to many chunks at once,
  writing an audit row per chunk.

Audits are stored in the `audits` table with before/after values for each
change.
