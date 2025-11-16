# Local Training vs Gen/Ask Runbook

This guide separates the **adapter training workflow** from the **`/gen/ask` serving workflow**, explains how to install dependencies without Docker, and shows how to reuse an existing MinIO deployment as the shared object store for both.

---

## 1. Dependencies & Environment

1. **Python 3.11** (required), Git, and build-essential/compilers (for PyTorch).
2. Create a virtual environment and install project requirements:

   ```bash
   python -m venv .venv
   source .venv/bin/activate            # Windows: .\.venv\Scripts\activate
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   pip install -r requirements-dev.txt  # optional but recommended for tooling/tests
   ```

   > Tip: if you use `uv`, run `uv pip install -r requirements.txt` instead for faster resolves.

3. Copy `.env.example` → `.env` and adjust values for your environment (DB URL, Redis, etc.).

---

## 2. Reusing an Existing MinIO/S3 Bucket

Both the training scripts and the `gen` service rely on the shared object store for:

- Reading dataset exports (`snapshot.jsonl`, etc.)
- Uploading trained adapter artifacts
- Serving signed URLs for exports/generation

Configure `.env` (or shell env vars) to point at your existing MinIO cluster:

```
MINIO_ENDPOINT=<host-or-ip>:<port>   # e.g. minio.company.net:9000
MINIO_ACCESS_KEY=<existing-access-key>
MINIO_SECRET_KEY=<existing-secret-key>
MINIO_SECURE=true|false              # false for http, true for https
S3_BUCKET=<bucket-name-used-by-both-training-and-gen>
```

> Make sure the bucket already exists and the credentials have read/write permissions.

---

## 3. Training Workflow (standalone)

The training CLI (`scripts/train_adapter.py`) reads a JSONL dataset from MinIO/local disk, fine-tunes an adapter, and uploads the resulting artifact back to the bucket.

1. **Export a dataset** (JSONL). If you already have one stored in MinIO, download it locally:

   ```bash
   aws --endpoint-url http://<minio-host>:<port> s3 cp s3://<bucket>/<path>/snapshot.jsonl data/snapshot.jsonl
   ```

2. **Run training** (example for SFT + DoRA):

   ```bash
   source .venv/bin/activate
   python scripts/train_adapter.py \
     --mode sft \
     --project-id <PROJECT_UUID> \
     --base-model microsoft/Phi-3-mini-4k-instruct \
     --data data/snapshot.jsonl \
     --output-dir outputs/run_phi3_sft \
     --epochs 1 \
     --lr 2e-4 \
     --batch-size 1 \
     --grad-accum 8 \
     --max-seq-len 1024 \
     --quantization int4 \
     --peft dora
   ```

   Optional flags:

   - `--document-id <DOC_UUID>` to scope bindings to a single document.
   - `--register-binding --model-ref my-doc-adapter` to register a binding immediately.
   - `--resume-from <checkpoint>` to continue a paused run.

3. On success you will see a payload such as:

   ```json
   {"adapter_id": "...", "metrics": {...}, "artifact": "s3://<bucket>/adapters/<run>.zip"}
   ```

   This confirms the adapter is stored in MinIO and registered in the DB.

---

## 4. Gen/Ask Service (standalone)

`scripts/serve_local.py` is the lightweight microservice that powers `/gen/ask`. It can run independently from the training job but will read adapters and datasets from the same MinIO bucket.

1. Ensure the `.env` used for gen has the same MinIO credentials/bucket as the training job and that migrations + seed data already exist.
2. Activate the virtualenv and start the service:

   ```bash
   source .venv/bin/activate
   python scripts/serve_local.py
   ```

   Environment knobs worth adjusting before launch:

   - `BASE_MODEL` (optional) to pin a local base HF model or GGUF.
   - `GEN_EVIDENCE_TOP_K`, `GEN_MIN_RANK_SCORE`, etc., for grounding behaviour.

3. Once the adapters from step 3 are registered (and optionally activated via `/adapters/activate`), you can call the API:

   ```bash
   curl -X POST http://localhost:9000/gen/ask \
     -H "Content-Type: application/json" \
     -d '{
       "project_id": "<PROJECT_UUID>",
       "document_id": "<DOC_UUID>",
       "prompt": "Summarize the escalation policy."
     }'
   ```

   The service will fetch grounding chunks from Postgres, stream evidence from MinIO if needed, and load the adapter artifact via the shared bucket.

---

## 5. Putting It Together

1. **Train adapters** as often as needed (Section 3) – each run uploads artifacts to MinIO and registers metadata in Postgres.
2. **Run `/gen/ask`** (Section 4) as a long-lived service. It stays hot, pulls whichever adapter is active, and uses the same MinIO bucket for artifacts and dataset snapshots.
3. **Switch adapters** without redeploying: call `POST /adapters/activate` to point the serving stack at a different training output.

This separation lets you iterate on training jobs offline (including on separate hardware) while keeping the inference service simple and always-online, all while sharing the existing MinIO storage backend.

---

### Troubleshooting

- **Adapter not loading:** verify the artifact URI logged by the trainer matches a real object in MinIO, and that the gen service credentials have read access.
- **Missing dependencies:** rerun the pip install commands in Section 1 or delete/ recreate `.venv`.
- **MinIO SSL errors:** set `MINIO_SECURE=true` *and* ensure `MINIO_ENDPOINT` omits `https://` (supply only host:port). For self-signed certs you may need to set `AWS_CA_BUNDLE`.

