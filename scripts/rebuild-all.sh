#!/bin/bash

set -Eeuo pipefail

PROJECT_DIR="${MLX_NOBBY_PROJECT_DIR:-$HOME/mlx-web}"
LOG_FILE="${MLX_NOBBY_REBOOT_LOG:-/tmp/mlx-nobby-rebuild.log}"

export PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/Applications/OrbStack.app/Contents/MacOS/xbin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

MLX_BIN="${MLX_BIN:-$HOME/bin/mlx}"
DOCKER_BIN="${DOCKER_BIN:-$(command -v docker || true)}"

exec >>"$LOG_FILE" 2>&1

ACTION="reboot"

AGENT_URL="${MLX_NOBBY_AGENT_URL:-http://127.0.0.1:8010}"
PORT_CHECK_BIN="${PORT_CHECK_BIN:-$(command -v lsof || true)}"
SERVICE_WAIT_TIMEOUT="${MLX_NOBBY_SERVICE_WAIT_TIMEOUT:-60}"
EXPECTED_PORTS="${MLX_NOBBY_REBOOT_PORTS:-8000 8010 8020 8030 8040 8050 8060 8090 11234}"
LIFECYCLE_REPORT_FILE="${MLX_NOBBY_LIFECYCLE_REPORT_FILE:-}"
CURRENT_STEP=0
TOTAL_STEPS=5
FAILED_PHASE="preparing"
AI_STOPPED=0
FAILURE_DETAIL=""

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
        "$error" \
        "$LIFECYCLE_REPORT_FILE" <<'PYREPORT' || true
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
    report_file,
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

if report_file:
    with open(report_file, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")
    raise SystemExit(0)

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

wait_for_port() {
    local port="$1"
    local attempts=$((SERVICE_WAIT_TIMEOUT * 2))
    local attempt

    for ((attempt = 1; attempt <= attempts; attempt++)); do
        if "$PORT_CHECK_BIN" -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.5
    done

    FAILURE_DETAIL="Port $port ist nach ${SERVICE_WAIT_TIMEOUT}s nicht erreichbar."
    echo "ERROR: $FAILURE_DETAIL"
    return 1
}

handle_error() {
    local exit_code=$?
    trap - ERR
    local error="System Reboot fehlgeschlagen in Phase ${FAILED_PHASE} (Exit ${exit_code})."
    if [ -n "$FAILURE_DETAIL" ]; then
        error="${error} ${FAILURE_DETAIL}"
    fi
    error="${error} Siehe ${LOG_FILE}."

    if [ "$AI_STOPPED" -eq 1 ]; then
        "$MLX_BIN" restart-all || error="${error} Wiederanlauf der Dienste ist ebenfalls fehlgeschlagen."
    fi

    report_lifecycle \
        "failed" \
        "$FAILED_PHASE" \
        "$CURRENT_STEP" \
        "$TOTAL_STEPS" \
        "$error" \
        "$error"
    exit "$exit_code"
}

trap handle_error ERR

echo
echo "============================================================"
echo "MLX NOBBY — SYSTEM REBOOT"
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

if [ -z "$PORT_CHECK_BIN" ] || [ ! -x "$PORT_CHECK_BIN" ]; then
    echo "ERROR: lsof executable not found"
    exit 127
fi

# Let the initiating HTTP response finish first.
sleep 1

echo
echo "===== STOP AI SERVICES ====="

FAILED_PHASE="stop-ai"
FAILURE_DETAIL="mlx stop-ai ist fehlgeschlagen."
CURRENT_STEP=0
report_lifecycle \
    "running" \
    "$FAILED_PHASE" \
    "$CURRENT_STEP" \
    "$TOTAL_STEPS" \
    "KI-Dienste werden sauber beendet; Agent und Control-Prozess bleiben aktiv."

"$MLX_BIN" stop-ai
AI_STOPPED=1

echo
echo "===== BUILD WEB IMAGE ====="

FAILED_PHASE="build-web"
FAILURE_DETAIL="docker compose build mlx-web ist fehlgeschlagen."
CURRENT_STEP=1
report_lifecycle \
    "running" \
    "$FAILED_PHASE" \
    "$CURRENT_STEP" \
    "$TOTAL_STEPS" \
    "Web-Image wird neu gebaut."

"$DOCKER_BIN" compose build mlx-web

echo
echo "===== FORCE RECREATE WEB ====="

FAILED_PHASE="recreate-web"
FAILURE_DETAIL="docker compose up --force-recreate mlx-web ist fehlgeschlagen."
CURRENT_STEP=2
report_lifecycle \
    "running" \
    "$FAILED_PHASE" \
    "$CURRENT_STEP" \
    "$TOTAL_STEPS" \
    "Web-Anwendung wird neu erstellt."

"$DOCKER_BIN" compose up -d \
    --force-recreate \
    mlx-web

echo
echo "===== RESTART LOCAL SERVICES ====="

FAILED_PHASE="restart-services"
FAILURE_DETAIL="mlx restart-all ist fehlgeschlagen."
CURRENT_STEP=3
report_lifecycle \
    "running" \
    "$FAILED_PHASE" \
    "$CURRENT_STEP" \
    "$TOTAL_STEPS" \
    "MLX-Dienste werden neu gestartet."

"$MLX_BIN" restart-all

echo
echo "===== VERIFY SERVICES ====="

FAILED_PHASE="verify-services"
FAILURE_DETAIL="Mindestens ein erwarteter Dienst ist nicht erreichbar."
CURRENT_STEP=4
report_lifecycle \
    "running" \
    "$FAILED_PHASE" \
    "$CURRENT_STEP" \
    "$TOTAL_STEPS" \
    "Erwartete Dienste und Ports werden geprüft."

for port in $EXPECTED_PORTS; do
    wait_for_port "$port"
done

AI_STOPPED=0
report_lifecycle \
    "completed" \
    "completed" \
    "$TOTAL_STEPS" \
    "$TOTAL_STEPS" \
    "MLX Nobby wurde neu gebaut und vollständig gestartet."

echo
echo "===== COMPLETE ====="
echo "$(date)"
