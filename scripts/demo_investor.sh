#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-11111111-1111-1111-1111-111111111111}"
DOCUMENT_ID="${DOCUMENT_ID:-22222222-2222-2222-2222-222222222222}"
API_URL="${API_URL:-http://localhost:9009}"
DATASET_PATH="${DATASET_PATH:-./demo_sft.jsonl}"

echo "== InstructifyAI investor demo =="
echo "Using PROJECT_ID=${PROJECT_ID}, DOCUMENT_ID=${DOCUMENT_ID}"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required for pretty-printing responses. Please install jq and re-run." >&2
  exit 1
fi

echo "== Ingest sample data (hook up your ingest script here) =="
# ./scripts/ingest_sample.sh || true

echo "== Simulate curation + export (replace with real LS workflow) =="
# ./scripts/ls_simulate_and_export.sh || true

echo "== Train & register two document-scoped adapters =="
python scripts/train_adapter.py \
  --mode sft \
  --project-id "${PROJECT_ID}" \
  --document-id "${DOCUMENT_ID}" \
  --base-model sshleifer/tiny-gpt2 \
  --model-ref doc-sft-a \
  --register-binding \
  --data "${DATASET_PATH}" \
  --epochs 1 \
  --batch-size 1 \
  --output-dir ./outputs/doc-sft-a || true

python scripts/train_adapter.py \
  --mode sft \
  --project-id "${PROJECT_ID}" \
  --document-id "${DOCUMENT_ID}" \
  --base-model sshleifer/tiny-gpt2 \
  --model-ref doc-sft-b \
  --register-binding \
  --data "${DATASET_PATH}" \
  --epochs 1 \
  --batch-size 1 \
  --output-dir ./outputs/doc-sft-b || true

echo "== Ask at project scope (legacy shape) =="
curl -s -X POST "${API_URL}/gen/ask" \
  -H 'Content-Type: application/json' \
  -d "{\"project_id\":\"${PROJECT_ID}\",\"prompt\":\"Give a one-line summary\"}" | jq .

echo "== Ask at document scope with multi-teacher vote (include_raw) =="
curl -s -X POST "${API_URL}/gen/ask" \
  -H 'Content-Type: application/json' \
  -d "{\"project_id\":\"${PROJECT_ID}\",\"document_id\":\"${DOCUMENT_ID}\",\"prompt\":\"Summarize section 3.2\",\"strategy\":\"vote\",\"top_k\":2,\"include_raw\":true}" | jq .

echo "== Ask with explicit model_refs override (concat) =="
curl -s -X POST "${API_URL}/gen/ask" \
  -H 'Content-Type: application/json' \
  -d "{\"project_id\":\"${PROJECT_ID}\",\"prompt\":\"List key risks\",\"model_refs\":[\"doc-sft-a\",\"doc-sft-b\"],\"strategy\":\"concat\",\"include_raw\":true}" | jq .

echo "== Demo complete =="
