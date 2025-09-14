#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   scripts/train_in_docker.sh --mode sft --project-id <UUID> --data /mnt/data/demo.jsonl \
#     --epochs 1 --prefer-small
#
# Pass any extra args; the script forwards them to scripts/train_auto.py.
#
# If you want to target a specific base model/quant, add:
#   BASE_MODEL=meta-llama/Llama-3-8B-Instruct QUANT=int4 scripts/train_in_docker.sh ...

# Start a one-off container and run the auto trainer
docker compose run --rm \
  --profile train \
  -e BASE_MODEL="${BASE_MODEL:-}" \
  -e QUANT="${QUANT:-}" \
  trainer bash -lc "python scripts/train_auto.py $*"

