#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:9009}"

echo "[smoke_gen] Hitting ${BASE_URL}/gen/info ..."
code=$(curl -sS -o /tmp/gen_info.$$ -w "%{http_code}" "${BASE_URL}/gen/info" || true)
if [[ "${code}" != "200" ]]; then
  echo "[smoke_gen] /gen/info HTTP ${code}" >&2
  cat /tmp/gen_info.$$ || true
  exit 1
fi
info_body=$(cat /tmp/gen_info.$$)
rm -f /tmp/gen_info.$$
echo "[smoke_gen] /gen/info response: ${info_body}"

# Best-effort backend extraction
backend=$(echo "${info_body}" | grep -o '"backend"\s*:\s*"[^"]*"' | sed -E 's/.*:\s*"([^"]*)"/\1/' || true)
echo "[smoke_gen] Backend: ${backend:-unknown}"

echo "[smoke_gen] Posting /gen/ask ..."
payload='{"project_id":"dev","prompt":"Say hello in one sentence.","max_new_tokens":64}'
code=$(curl -sS -o /tmp/gen_ask.$$ -w "%{http_code}" -H 'Content-Type: application/json' \
  -X POST "${BASE_URL}/gen/ask" -d "${payload}" || true)
body=$(cat /tmp/gen_ask.$$ || true)
rm -f /tmp/gen_ask.$$
if [[ "${code}" != "200" ]]; then
  echo "[smoke_gen] /gen/ask HTTP ${code}" >&2
  echo "[smoke_gen] body: ${body}" >&2
  exit 1
fi

# Require non-empty answer field
answer=$(echo "${body}" | grep -o '"answer"\s*:\s*"[^\"]*' | sed -E 's/.*:\s*"(.*)/\1/' || true)
if [[ -z "${answer}" ]]; then
  echo "[smoke_gen] Empty answer field in response" >&2
  echo "[smoke_gen] body: ${body}" >&2
  exit 1
fi

echo "[smoke_gen] OK"
exit 0
