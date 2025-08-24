#!/usr/bin/env bash
set -euo pipefail
BASE="${BASE:-http://localhost:8000}"
TOKEN="${TOKEN:-}"
PROJECT_ID="${PROJECT_ID:-}"
PDF_FILE="${PDF_FILE:-examples/pdfs/sample.pdf}"
ZIP_FILE="${ZIP_FILE:-examples/bundles/report_small.zip}"
EXPORT_PRESET="${EXPORT_PRESET:-rag}"
auth_flag=()
if [[ -n "$TOKEN" ]]; then auth_flag=(-H "Authorization: Bearer $TOKEN"); else auth_flag=(-H "X-Role: curator"); fi
json() { jq -r "$1"; }
say() { echo -e "\n▸ $*"; }
say "Checking API health at $BASE/health"
curl -fsS "${auth_flag[@]}" "$BASE/health" | jq .
if [[ -z "${PROJECT_ID}" ]]; then
  say "Attempting to list projects to auto-pick PROJECT_ID"
  if curl -fsS "${auth_flag[@]}" "$BASE/projects" >/tmp/projects.json 2>/dev/null; then
    PROJECT_ID="$(jq -r '.projects[0].id // empty' /tmp/projects.json)"
  else PROJECT_ID=""; fi
fi
if [[ -z "${PROJECT_ID}" ]]; then echo "ERROR: PROJECT_ID not set and /projects unavailable/empty."; exit 1; fi
say "Using PROJECT_ID=$PROJECT_ID"
if [[ ! -f "$PDF_FILE" ]]; then echo "PDF_FILE '$PDF_FILE' not found."; exit 1; fi
say "Ingesting PDF $PDF_FILE"
resp=$(curl -fsS "${auth_flag[@]}" -F "project_id=$PROJECT_ID" -F "file=@${PDF_FILE}" "$BASE/ingest")
DOC_ID=$(echo "$resp" | json '.doc_id')
echo "DOC_ID=$DOC_ID"
say "Waiting for parse completion for DOC_ID=$DOC_ID"
max_tries=60; sleep_secs=2
for i in $(seq 1 $max_tries); do
  row=$(curl -fsS "${auth_flag[@]}" "$BASE/documents?project_id=${PROJECT_ID}&limit=200" | jq -c --arg id "$DOC_ID" '.documents[] | select(.id==$id)')
  if [[ -n "$row" ]]; then
    meta=$(echo "$row" | jq -c '.metadata'); has_parse=$(echo "$meta" | jq -r 'has("parse")'); status=$(echo "$row" | jq -r '.status')
    echo "  try=$i status=$status parse_field=$has_parse"; if [[ "$has_parse" == "true" ]]; then break; fi
  fi; sleep "$sleep_secs"
done
if [[ "$has_parse" != "true" ]]; then echo "ERROR: parsing timeout."; exit 1; fi
say "Fetching document metrics"
curl -fsS "${auth_flag[@]}" "$BASE/documents/${DOC_ID}/metrics" | jq .
say "Exporting JSONL with preset=$EXPORT_PRESET"
payload=$(jq -n --arg pid "$PROJECT_ID" --arg did "$DOC_ID" --arg preset "$EXPORT_PRESET" '{project_id:$pid, doc_ids:[$did], preset:$preset}')
exp_resp=$(curl -fsS "${auth_flag[@]}" -H "Content-Type: application/json" -d "$payload" "$BASE/export/jsonl")
echo "$exp_resp" | jq .; url=$(echo "$exp_resp" | jq -r '.url'); if [[ -z "$url" || "$url" == "null" ]]; then echo "No export URL"; exit 1; fi
say "Downloading export"; curl -fsS -L "$url" -o /tmp/export.jsonl; head -n 3 /tmp/export.jsonl || true
if [[ -f "$ZIP_FILE" ]]; then
  say "Ingesting HTML ZIP bundle $ZIP_FILE"
  resp2=$(curl -fsS "${auth_flag[@]}" -F "project_id=$PROJECT_ID" -F "file=@${ZIP_FILE}" "$BASE/ingest/zip"); DOC2_ID=$(echo "$resp2" | json '.doc_id'); echo "DOC2_ID=$DOC2_ID"
else echo "Skipping ZIP ingest; file '$ZIP_FILE' not found."; fi
say "E2E smoke complete ✅"
