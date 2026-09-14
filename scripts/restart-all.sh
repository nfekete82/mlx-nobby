#!/bin/bash

set -euo pipefail

PROJECT_DIR="${MLX_NOBBY_PROJECT_DIR:-$HOME/mlx-web}"
LOG_FILE="/tmp/mlx-nobby-restart.log"

export PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/Applications/OrbStack.app/Contents/MacOS/xbin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

MLX_BIN="${MLX_BIN:-$HOME/bin/mlx}"

exec >>"$LOG_FILE" 2>&1

echo
echo "============================================================"
echo "MLX NOBBY — RESTART ALL"
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

echo "mlx: $MLX_BIN"

# Let the initiating HTTP response leave the agent before restarting it.
sleep 1

echo
echo "===== RESTART SERVICES ====="

"$MLX_BIN" restart-all

echo
echo "===== COMPLETE ====="
echo "$(date)"
