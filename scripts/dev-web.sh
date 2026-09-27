#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export MLX_NOBBY_BUILD_SHA="$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || printf 'unknown')"

COMPOSE=(
  docker compose
  -f docker-compose.yml
  -f docker-compose.dev.yml
)

echo "Starting MLX Nobby web development environment..."
echo "Revision: $MLX_NOBBY_BUILD_SHA"

"${COMPOSE[@]}" up -d --no-deps mlx-web

CID=$("${COMPOSE[@]}" ps -q mlx-web)

if [[ -z "$CID" ]]; then
    echo "ERROR: mlx-web container is not running."
    exit 1
fi

MOUNT=$(docker inspect "$CID" \
  --format '{{range .Mounts}}{{if eq .Destination "/app/frontend"}}{{.Source}} -> {{.Destination}} ({{.Mode}}){{end}}{{end}}')

if [[ -z "$MOUNT" ]]; then
    echo "ERROR: frontend live mount is not active."
    exit 1
fi

echo "Frontend live mount:"
echo "  $MOUNT"

echo
echo "Waiting for MLX Nobby..."

for i in {1..30}; do
    if curl -fsS http://127.0.0.1:8090/ >/dev/null 2>&1; then
        echo "MLX Nobby is ready:"
        echo "  http://127.0.0.1:8090"
        echo
        echo "Frontend changes are live. No Docker rebuild required."
        exit 0
    fi

    sleep 1
done

echo "ERROR: MLX Nobby did not become ready within 30 seconds."
exit 1
