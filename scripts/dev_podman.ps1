param(
  [switch]$Rebuild
)

# Ensure COMPOSE_PROVIDER uses Podman (not docker-compose shim)
$env:COMPOSE_PROVIDER = "podman"

Write-Host "[podman] Checking Podman machine..."
try {
  $machine = podman machine inspect 2>$null | Out-String
} catch {
  Write-Host "[podman] Initializing VM (first run)"
  podman machine init --cpus 6 --memory 8192 --disk-size 60
}

podman machine start | Out-Null

if ($Rebuild) {
  Write-Host "[compose] Building images..."
  podman compose build
}

Write-Host "[compose] Starting stack..."
podman compose up -d

Write-Host "[migrate] Applying Alembic migrations in api container..."
podman compose exec -T api alembic upgrade head

Write-Host "[compose] Services:"
podman compose ps

Write-Host "[logs] Tailing api + worker (Ctrl+C to stop)"
podman compose logs -f api worker

