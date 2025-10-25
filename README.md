# InstructifyAI

[![CI](https://github.com/InstructifyAI/InstructifyAI/actions/workflows/ci.yml/badge.svg)](https://github.com/InstructifyAI/InstructifyAI/actions/workflows/ci.yml)
[![Coverage](coverage.svg)](coverage.svg)
![Status](https://img.shields.io/badge/status-active-brightgreen)
![License](https://img.shields.io/badge/license-private-lightgrey)

## InstructifyAI — Private Curation + Mini-LLM Adapters (on your data)

**What it is:** A privacy-first platform that helps teams **curate**, **label**, and **adapt** small LLMs to their own documents—then answer questions with **document-scoped** routing and **multi-teacher** ensembles.

**Who it's for (ICPs):**
- Regulated enterprises (Finance, Insurance, Healthcare) with sensitive policy/procedure docs
- Legal/Compliance teams needing provenance and auditability
- Tech orgs wanting local, resource-aware LLMs without sending data to external SaaS

**Why now:**
- Generic LLMs hallucinate on domain policy; curated, doc-specific adapters are cheaper, faster, and more accurate for internal knowledge.

**What’s unique:**
- **Human-in-the-loop curation** with Label Studio (audits + scorecards)
- **Doc-scoped adapters** with **multi-teacher** aggregation (`first | vote | concat | rerank*`)
- **Runs locally** (CPU or GPU) with **resource-aware** serving (HF + optional llama.cpp)

---

## 7-minute live demo (end-to-end)
1) Ingest + auto-chunk a small corpus (policies).
2) Open Label Studio; accept a few suggestions → webhooks create **audits**.
3) Export JSONL → train **two** adapters bound to one `document_id`.
4) Ask with `/gen/ask` at **document scope**, using `strategy=vote` and `include_raw=true`.

Run it:
```bash
make demo-investor
```

**Outcomes to show:** time-to-first-answer (~minutes), better doc-specific answers vs. project baseline, and transparent model votes.

---

## Value checklist (for buyers)

* **Speed**: go from raw docs → curated adapters in hours, **no GPUs required**.
* **Quality**: doc-scoped adapters beat generic models on internal policy Q&A.
* **Control**: keeps data in your infra; **audited** labeling + versioned taxonomies.

> *Note:* LoRA/QLoRA/DoRA apply on HF backend; llama.cpp runs base models only.

## Documentation

- [Project Achievements](ACHIEVEMENTS.md)
- [Architecture & Data Flow](docs/architecture.md)
- [Product Datasheet](docs/datasheet.md)
- [Security Notes](docs/security.md)
- [ROI Worksheet](docs/roi.md)
- [Competitive Comparison](docs/comparison.md)
- [Roadmap](docs/roadmap.md)
- [Case Study Template](docs/case-studies/template.md)
- [OpenAPI export instructions](docs/openapi/README.md)

## Quick Start (Docker Desktop / WSL2 & macOS)

1. Ensure Docker Desktop is running. On Windows, use a WSL2 terminal; on macOS use the native shell.
2. Start the stack (Docker Desktop):
   ```bash
   make dev
   ```
   If you change worker dependencies or the Dockerfile, rebuild the image (run in WSL on Windows):
   ```bash
   docker compose build worker
   ```
3. Apply database migrations:
   ```bash
   make migrate
   ```
4. (Optional) Run the demo on bundled samples:
   ```bash
   make demo
   ```
5. Launch Label Studio and configure the webhook:
   - `docker run -it -p 8080:8080 heartexlabs/label-studio:latest`
   - Set `LS_BASE_URL` and `LS_API_TOKEN` in your `.env` to point to the instance.
   - Open <http://localhost:8080> and add a webhook pointing to `http://host.docker.internal:8000/webhooks/label-studio`.
6. Import the Postman collection and environment from `docs/postman/` or try the API with curl:
   ```bash
   curl http://localhost:8000/health
   curl -H "X-Role: viewer" "http://localhost:8000/projects?limit=20&offset=0&q=dev"
   curl -X POST http://localhost:8000/export/jsonl \
     -H "Authorization: Bearer $JWT" \
     -H "Content-Type: application/json" \
     -d '{"doc_ids":["DOC_ID"]}'
   ```

## Running with Podman (Windows/macOS/Linux)

On Windows/macOS, Podman runs inside a lightweight VM (podman machine). To use Podman instead of Docker:

1) Initialize and start the VM (first time only on Windows/macOS):

```
podman machine init --cpus 6 --memory 8192 --disk-size 60
podman machine start
```

2) Ensure `podman compose` uses the Podman provider (avoid Docker Compose shim):

PowerShell (current session):

```
$env:COMPOSE_PROVIDER = "podman"
```

Persist (optional):

```
setx COMPOSE_PROVIDER podman
```

3) Build and start services:

```
podman compose build
podman compose up -d
```

4) Run migrations:

```
podman compose exec -T api alembic upgrade head
```

Notes
- If you prefer, install the Python wrapper: `pipx install podman-compose` and use `podman-compose up -d`.
- GPU passthrough is typically unavailable on Podman machine for Windows/macOS; services run on CPU.
- A `.dockerignore` is included to reduce context size and avoid copying `.env` into images.

## Curation API

Phase‑1 exposes endpoints for managing a per‑project taxonomy and for applying
curation metadata to chunks. Endpoints require an `Authorization: Bearer <jwt>`
header with a `role` claim. In `ENV=DEV`, you may override the role using
`X-Role`. Only `curator` may modify data while `viewer` can read.

* `POST /projects` – create a new project and return its `id`.
* `PUT /projects/{project_id}/taxonomy` – create a new taxonomy version with
  field definitions including `helptext` and `examples`.
* `GET /projects/{project_id}/taxonomy/guidelines` – return labeling guidelines
  (JSON or markdown) for the active taxonomy.
* `POST /label-studio/config?project_id=...` – render a Label Studio project configuration from the active taxonomy; paste the XML into Label Studio's "Labeling configuration" panel under Settings → Labeling Interface.
* `POST /webhooks/label-studio` – apply a metadata patch from a Label Studio
  webhook and append an audit entry.
* `POST /chunks/bulk-apply` – apply a metadata patch to many chunks at once,
  selecting by `chunk_ids` or `doc_id`+`range`; writes an audit row per chunk.
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

## Mini‑LLM Training (Pluggable)

This repo includes an optional, interface‑driven stack for low‑cost adapters (SFT, MFT, ORPO) with DoRA/LoRA/QLoRA and an experimental RWKV backend. It is disabled by default at the main API level to avoid scope drift.

- Enable adapters API in main app by setting `ENABLE_ADAPTERS_API=true` (env), or in `.env` set `ENABLE_ADAPTERS_API=True`. This maps to `Settings.enable_adapters_api`.
- Alternatively, use the standalone local server: `python scripts/serve_local.py` (does not require modifying the main API).

Quick start:
- Train: `python scripts/train_adapter.py --mode sft --project-id <PID> --base-model sshleifer/tiny-gpt2 --peft dora --quantization fp32 --data ./demo_sft.jsonl --epochs 1 --batch-size 1 --grad-accum 1 --output-dir ./outputs/demo_sft`
- Serve locally: `BASE_BACKEND=hf QUANT=fp32 python scripts/serve_local.py`
- Ask: `curl -s -X POST http://localhost:9009/gen/ask -H 'Content-Type: application/json' -d '{"project_id":"<PID>","prompt":"Summarize policy ABC section 3.2."}'`

Run API with adapters API enabled via Makefile:
- `make dev-adapters` (uses `docker-compose.adapters.yml` to set `ENABLE_ADAPTERS_API=true`)

Folders:
- `training/` builders, trainers, and PEFT strategies
- `backends/` HF and RWKV runners
- `registry/` adapters models + storage helpers
- `scripts/` training, adapter registration, and local serving

## Docker GPU/CPU Options

- Optional GPU override file: `docker-compose.gpu.yml` can be used alongside the base compose file to request GPU resources (e.g., for a generation service named `gen`). Example usage:

  ```bash
  docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
  ```

- Optional llama.cpp backend (CPU build): the base image can optionally install `llama-cpp-python` via a build arg so you can use the `llama_cpp` backend in `scripts/serve_local.py` without forcing it everywhere. Set `ENABLE_LLAMA_CPP=1` at build time:

  ```bash
  # Build with llama.cpp CPU bindings enabled
  docker build . -t instructifyai-api:cpu-llama \
    --build-arg ENABLE_LLAMA_CPP=1

  # Or with compose
  DOCKER_BUILDKIT=1 docker compose build \
    --build-arg ENABLE_LLAMA_CPP=1
  ```

  When omitted (`ENABLE_LLAMA_CPP=0`, default), the image skips `llama-cpp-python` and the llama.cpp backend is unavailable inside the container.

## Resource-aware Serving

The local generator server (`scripts/serve_local.py`) is resource-aware:
- If `BASE_MODEL` is not set, it detects hardware (CPU/GPU/VRAM) and recommends a backend and base model (HF or llama.cpp GGUF) with a safe token cap.
- If `BASE_MODEL` is set, it respects your choice and uses `BASE_BACKEND=hf|llama_cpp` and `QUANT` if provided.

Run the generator service (compose example):

```bash
# Build and run the generation service
docker compose up -d --build gen

# Inspect hardware and chosen model/backend
curl -s http://localhost:9009/gen/info | jq .

# Ask a quick question (replace <PROJECT_ID> as needed)
curl -s -X POST http://localhost:9009/gen/ask \
  -H 'Content-Type: application/json' \
  -d '{"project_id":"<PROJECT_ID>","prompt":"Say hello."}'

# Optional: enable GPU reservations via override
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d gen
```

Notes:
- Adapters (LoRA/QLoRA/DoRA) apply only on the HF backend. The llama.cpp backend ignores adapters.
- If using llama.cpp, ensure the GGUF file is present and `BASE_MODEL` points to the local path, or rely on HF backend by setting `BASE_BACKEND=hf` and a valid HF base.

## Doc-specific & Multi-teacher Ask

`/gen/ask` remains backward compatible: `{"project_id","prompt"}` requests still return `{"answer":"..."}` and require no extra configuration. When `FEATURE_DOC_BINDINGS=false`, routing stays project-wide exactly as before. When enabled (default), you can opt into document bindings, ensembles, and explicit overrides using these optional fields:

- `document_id`: prefer document-scoped bindings; falls back to project scope when no binding exists (we log when the fallback happens)
- `model_refs`: run the listed bindings in order, bypassing registry selection
- `strategy`: `first` (default), `vote`, `concat`, `rerank` (stub = longest text)
- `top_k`: limit auto-selected bindings (default `2`)
- `include_raw`: append `raw/strategy/used` without changing the base schema (default `false`)

`doc_id` requests are still accepted for backward compatibility, but we normalize them to `document_id` and emit a deprecation log; update your clients when convenient.

Examples:

```bash
# 1) Legacy project-only request (unchanged)
curl -s -X POST http://localhost:9009/gen/ask \
  -H 'Content-Type: application/json' \
  -d '{"project_id":"<PROJECT_ID>","prompt":"Summarize section 3."}'

# 2) Document binding with vote strategy + raw payload
curl -s -X POST http://localhost:9009/gen/ask \
  -H 'Content-Type: application/json' \
  -d '{"project_id":"<PROJECT_ID>","document_id":"<DOC_ID>","prompt":"List key risks.","strategy":"vote","include_raw":true,"top_k":2}'

# 3) Explicit teacher override, concatenating their outputs
curl -s -X POST http://localhost:9009/gen/ask \
  -H 'Content-Type: application/json' \
  -d '{"project_id":"<PROJECT_ID>","prompt":"Draft a friendly reply.","model_refs":["contracts-sft-v1","contracts-mft-v2"],"strategy":"concat","include_raw":true}'
```

Trainer bindings (LoRA/QLoRA/DoRA) can now be registered directly to a document:

```bash
python scripts/train_adapter.py \
  --mode sft \
  --project-id "$PROJECT_ID" \
  --document-id "$DOCUMENT_ID" \
  --model-ref "doc-finetune-v1" \
  --register-binding \
  --base-model microsoft/Phi-3-mini-4k-instruct \
  --data /tmp/doc_dataset.jsonl
```

LoRA/QLoRA/DoRA adapters activate only on HF bindings; llama.cpp bindings ignore `adapter_path` (we log a warning once). `FEATURE_DOC_BINDINGS=true` by default—set it to `false` to force the legacy single-teacher route.

## API Reference

* **OpenAPI JSON:** see `docs/openapi/openapi.json` (export from your running API)
* **Postman Collection:** see `docs/postman/InstructifyAI.postman_collection.json`

### /gen/ask request (canonical fields)

Required: `project_id`, `prompt`  
Optional: `document_id`, `strategy`, `top_k`, `model_refs[]`, `include_raw`

> Back-compat: `doc_id` is accepted but **deprecated**; the server maps it to `document_id`.

### Production Security Notes

- Disable the DEV-only `X-Role` override in production deployments; rely on proper JWT claims/roles instead.
- Verify Label Studio webhook payloads with HMAC signatures before accepting curator edits; reject unsigned/invalid requests.
- Harden storage access: use scoped S3/MinIO policies, server-side encryption, and reasonable request-size limits when exchanging artifacts over `/gen/ask`, `/ingest`, or webhooks.
## Docker/Podman — CPU/GPU Quickstart

The stack supports lean CPU builds by default and optional GPU builds for ML services (`gen`, `trainer`). Heavy ML deps are installed once at image build and models are prefetched into the image for fast startup.

Environment knobs
- `ML_VARIANT`: `cpu` (default) or `gpu` for `gen`/`trainer` images.
- `BASE_MODEL`: HF model to prefetch at build (default `Phi-3-mini-4k-instruct`).

Docker (CPU, default)
- Build and start core stack:
  - `docker compose build`
  - `docker compose up -d postgres redis minio`
  - `docker compose up -d api worker flower labelstudio`
- Optional services:
  - OCR worker: `docker compose up -d worker_ocr`
  - ML services: `docker compose up -d gen trainer`

Docker (GPU for ML services)
- Build ML image with CUDA wheels and start ML services:
  - `ML_VARIANT=gpu docker compose build gen trainer`
  - `ML_VARIANT=gpu docker compose up -d gen trainer`

Change default model and prefetch
- Rebuild ML image with a different HF model:
  - `BASE_MODEL=meta-llama/Llama-3.2-1B-Instruct docker compose build gen trainer`

Podman
- CPU default:
  - `make dev-podman` (builds and starts the stack)
- GPU for ML services (host must have NVIDIA hooks configured):
  - `ML_VARIANT=gpu make dev-podman`

Windows (Podman) tips
- Force Podman’s compose engine (avoid Docker Compose fallback):
  - PowerShell (per session): `$env:COMPOSE_PROVIDER="podman"`
  - Then: `podman compose build` / `podman compose up -d ...`
- If you still see a credential helper error like `docker-credential-desktop`:
  - Create a minimal Docker config and point DOCKER_CONFIG to it:
    - `mkdir .docker-config && echo {} > .docker-config/config.json`
    - PowerShell: `$env:DOCKER_CONFIG=(Resolve-Path ".\.docker-config").Path`
  - Or install/use `podman-compose` explicitly: `podman-compose up -d --build`

Notes
- `gen` and `trainer` share a single image tag (`instructify-ml:latest`) and are built once.
- HF caches are baked into the image at `/opt/hf`; services set `HF_HOME` and `TRANSFORMERS_CACHE` to point there.
- If you change `BASE_MODEL`, rebuild `gen`/`trainer` to prefetch the new model.

Make targets (auto GPU/CPU)
- Docker:
  - Build ML image with auto-detect: `make build-ml-auto`
  - Start ML services with auto-detect: `make up-ml-auto`
  - Build+start: `make dev-ml-auto`
- Podman:
  - Build ML image with auto-detect: `make build-ml-auto-podman`
  - Start ML services with auto-detect: `make up-ml-auto-podman`
  - Build+start: `make dev-ml-auto-podman`
These detect `nvidia-smi`; if present, they set `ML_VARIANT=gpu`, otherwise `cpu`.
