#!/bin/bash

set -euo pipefail

PROJECT_DIR="${MLX_NOBBY_PROJECT_DIR:-$HOME/mlx-web}"
LOG_FILE="/tmp/mlx-nobby-shutdown-ai.log"
export PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
MLX_BIN="${MLX_BIN:-$HOME/bin/mlx}"
AGENT_URL="${MLX_NOBBY_AGENT_URL:-http://127.0.0.1:8010}"

exec >>"$LOG_FILE" 2>&1

report_lifecycle() {
    python3 - "$AGENT_URL" "$1" "$2" "$3" "$4" "$5" <<'PYREPORT' || true
import json
import sys
import urllib.request

agent_url, state, phase, current, total, message = sys.argv[1:]
request = urllib.request.Request(
    agent_url.rstrip("/") + "/api/system/lifecycle/progress",
    data=json.dumps({
        "action": "shutdown-ai", "state": state, "phase": phase,
        "current": int(current), "total": int(total), "message": message,
    }).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=2) as response:
    response.read()
PYREPORT
}

cd "$PROJECT_DIR"
if [ ! -x "$MLX_BIN" ]; then
    MLX_BIN="$(command -v mlx || true)"
fi
if [ -z "$MLX_BIN" ] || [ ! -x "$MLX_BIN" ]; then
    echo "ERROR: mlx executable not found"
    exit 127
fi

sleep 1
report_lifecycle "running" "stop-ai" 1 2 "KI- und Modell-Dienste werden beendet."
"$MLX_BIN" stop-ai
report_lifecycle "completed" "completed" 2 2 "KI-System wurde beendet; die Web-Oberfläche bleibt verfügbar."
