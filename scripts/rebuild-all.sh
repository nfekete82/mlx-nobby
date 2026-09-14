#!/bin/bash

set -euo pipefail

PROJECT_DIR="${MLX_NOBBY_PROJECT_DIR:-$HOME/mlx-web}"
LOG_FILE="/tmp/mlx-nobby-rebuild.log"

export PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/Applications/OrbStack.app/Contents/MacOS/xbin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

MLX_BIN="${MLX_BIN:-$HOME/bin/mlx}"
DOCKER_BIN="${DOCKER_BIN:-$(command -v docker || true)}"

exec >>"$LOG_FILE" 2>&1

echo
echo "============================================================"
echo "MLX NOBBY — REBUILD ALL"
echo "$(date)"
echo "============================================================"

cd "$PROJECT_DIR"

if [ ! -x "$MLX_BIN" ]; then
    MLX_BIN="$(command -v mlx || true)"
fi

if [ -z "$MLX_BIN" ] || [ ! -x "$MLX_BIN" ]; then
    echo "ERROR: mlx executable not found"
    exit 127
fi

if [ -z "$DOCKER_BIN" ] || [ ! -x "$DOCKER_BIN" ]; then
    echo "ERROR: docker executable not found"
    exit 127
fi

echo "mlx:    $MLX_BIN"
echo "docker: $DOCKER_BIN"

# Let the initiating HTTP response finish first.
sleep 1

echo
echo "===== REBUILD WEB ====="

"$DOCKER_BIN" compose up -d \
    --build \
    --force-recreate \
    mlx-web

echo
echo "===== RESTART LOCAL SERVICES ====="

"$MLX_BIN" restart-all

echo
echo "===== COMPLETE ====="
echo "$(date)"
