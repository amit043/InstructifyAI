#!/usr/bin/env bash
set -euo pipefail

# Ensure podman compose is the provider (avoid docker-compose shim)
export COMPOSE_PROVIDER=podman

if podman machine ls >/dev/null 2>&1; then
  # On macOS/Windows, start the VM (Linux hosts may not have podman machine)
  if ! podman machine inspect >/dev/null 2>&1; then
    echo "[podman] Initializing VM (first run)"
    podman machine init --cpus 6 --memory 8192 --disk-size 60
  fi
  podman machine start || true
fi

if [[ "${REBUILD:-0}" == "1" ]]; then
  echo "[compose] Building images..."
  podman compose build
fi

echo "[compose] Starting stack..."
podman compose up -d

echo "[migrate] Applying Alembic migrations in api container..."
podman compose exec -T api alembic upgrade head

echo "[compose] Services:"
podman compose ps

echo "[logs] Tailing api + worker (Ctrl+C to stop)"
podman compose logs -f api worker

