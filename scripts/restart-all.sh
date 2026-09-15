#!/bin/bash

set -euo pipefail

PROJECT_DIR="${MLX_NOBBY_PROJECT_DIR:-$HOME/mlx-web}"
LOG_FILE="/tmp/mlx-nobby-restart.log"

export PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/Applications/OrbStack.app/Contents/MacOS/xbin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

MLX_BIN="${MLX_BIN:-$HOME/bin/mlx}"

exec >>"$LOG_FILE" 2>&1

ACTION="restart-all"

AGENT_URL="${MLX_NOBBY_AGENT_URL:-http://127.0.0.1:8010}"

report_lifecycle() {
    local state="$1"
    local phase="$2"
    local current="$3"
    local total="$4"
    local message="$5"
    local error="${6:-}"

    python3 - \
        "$AGENT_URL" \
        "$ACTION" \
        "$state" \
        "$phase" \
        "$current" \
        "$total" \
        "$message" \
        "$error" <<'PYREPORT' || true
import json
import sys
import urllib.request

(
    agent_url,
    action,
    state,
    phase,
    current,
    total,
    message,
    error,
) = sys.argv[1:]

payload = {
    "action": action,
    "state": state,
    "phase": phase,
    "current": int(current),
    "total": int(total),
    "message": message,
    "error": error or None,
}

request = urllib.request.Request(
    agent_url.rstrip("/")
    + "/api/system/lifecycle/progress",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urllib.request.urlopen(
    request,
    timeout=2,
) as response:
    response.read()
PYREPORT
}

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

report_lifecycle \
    "running" \
    "restart-services" \
    1 \
    2 \
    "MLX-Dienste werden neu gestartet."

"$MLX_BIN" restart-all

report_lifecycle \
    "completed" \
    "completed" \
    2 \
    2 \
    "Alle MLX-Dienste wurden neu gestartet."

echo
echo "===== COMPLETE ====="
echo "$(date)"
