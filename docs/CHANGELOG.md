# Change Log

## 2025-10-06
- Added the `adapter_bindings` table plus registry helpers so `/gen/ask` can look up document-scoped or project-scoped teachers, support ensemble strategies, explicit `model_refs`, and include raw per-model outputs without breaking legacy clients.
- `FEATURE_DOC_BINDINGS` flag (default on) gates the new routing path; when disabled the generator behaves exactly as before.
- `scripts/train_adapter.py` gained `--doc-id/--model-ref/--tag/--register-binding` to register bindings straight from the trainer (including backend/base/adapter metadata).
- README documents the new doc-specific + multi-teacher flows with curl examples; `scripts/smoke_gen.sh` now checks the `answer` field returned by `/gen/ask`.
- Standardized the doc-specific routing/registry/training stack on the `document_id` naming convention (new Alembic migration `0021`), while preserving backward compatibility for existing `doc_id` payloads.

## 2025-10-03
- Training run APIs now validate optional document_id against the project and propagate it through the trainer/registry so per-document models can be registered and resolved by the generation service (document routing + ensemble support). The create endpoint now accepts both `document_id` and ingestion-style `doc_id` payload keys.

## 2025-09-20
- Auto-materialize dataset snapshots when training runs are requested so the training runs endpoint no longer fails (commit "feat(training): auto-materialize dataset snapshots") if a curator skips the manual materialize step.
- Training runs now execute via the Celery-backed trainer service (commit pending) so PyTorch stays outside the API container and background jobs run with ML deps. Trainer worker now performs dependency/object-store preflight (API no longer blocks on peft check) and run failure bubbles through Celery.


