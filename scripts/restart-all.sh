#!/bin/bash

set -euo pipefail

PROJECT_DIR="${MLX_NOBBY_PROJECT_DIR:-$HOME/mlx-web}"
LOG_FILE="/tmp/mlx-nobby-restart.log"

export PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/Applications/OrbStack.app/Contents/MacOS/xbin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

MLX_BIN="${MLX_BIN:-$HOME/bin/mlx}"

exec >>"$LOG_FILE" 2>&1

ACTION="restart-all"

AGENT_URL="${MLX_NOBBY_AGENT_URL:-http://127.0.0.1:8010}"
AGENT_LABEL="de.nobby.mlx-agent"
AGENT_PLIST="$HOME/Library/LaunchAgents/${AGENT_LABEL}.plist"
IMAGE_URL="${MLX_NOBBY_IMAGE_URL:-http://127.0.0.1:8030}"
IMAGE_LABEL="de.nobby.mlx-images"
IMAGE_PLIST="$HOME/Library/LaunchAgents/${IMAGE_LABEL}.plist"
LAUNCHD_DOMAIN="gui/$(id -u)"

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

wait_agent_unloaded() {
    local attempt
    for attempt in $(seq 1 100); do
        if ! launchctl print "$LAUNCHD_DOMAIN/$AGENT_LABEL" >/dev/null 2>&1 && \
           ! lsof -tiTCP:8010 -sTCP:LISTEN >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.1
    done

    echo "ERROR: Agent wurde nach bootout nicht rechtzeitig vollständig entladen."
    return 1
}

wait_agent_ready() {
    local attempt
    for attempt in $(seq 1 200); do
        if lsof -tiTCP:8010 -sTCP:LISTEN >/dev/null 2>&1 && \
           curl -fsS --connect-timeout 1 --max-time 2 \
               "$AGENT_URL/api/status" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.1
    done

    echo "ERROR: Agent wurde nach dem Reload nicht rechtzeitig bereit."
    return 1
}

wait_image_unloaded() {
    local attempt
    for attempt in $(seq 1 100); do
        if ! launchctl print "$LAUNCHD_DOMAIN/$IMAGE_LABEL" >/dev/null 2>&1 && \
           ! lsof -tiTCP:8030 -sTCP:LISTEN >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.1
    done

    echo "ERROR: Image-Service wurde nach bootout nicht rechtzeitig vollständig entladen."
    return 1
}

wait_image_ready() {
    local attempt
    for attempt in $(seq 1 300); do
        if launchctl print "$LAUNCHD_DOMAIN/$IMAGE_LABEL" >/dev/null 2>&1 && \
           lsof -tiTCP:8030 -sTCP:LISTEN >/dev/null 2>&1 && \
           curl -fsS --connect-timeout 1 --max-time 2 \
               "$IMAGE_URL/health" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.1
    done

    echo "ERROR: Image-Service wurde nicht rechtzeitig bereit."
    return 1
}

ensure_image_launchagent_ready() {
    if wait_image_ready; then
        echo "Image-Service ist bereit."
        return 0
    fi

    if [ ! -f "$IMAGE_PLIST" ]; then
        echo "ERROR: Image LaunchAgent fehlt: $IMAGE_PLIST"
        return 1
    fi

    echo "Image-Service ist nach restart-all nicht bereit; LaunchAgent wird repariert..."

    if launchctl print "$LAUNCHD_DOMAIN/$IMAGE_LABEL" >/dev/null 2>&1; then
        launchctl bootout "$LAUNCHD_DOMAIN/$IMAGE_LABEL" || true
    fi

    wait_image_unloaded || return 1

    local attempt
    local bootstrap_ok=0
    for attempt in $(seq 1 20); do
        if launchctl bootstrap "$LAUNCHD_DOMAIN" "$IMAGE_PLIST"; then
            bootstrap_ok=1
            break
        fi
        echo "Image bootstrap Versuch $attempt fehlgeschlagen; neuer Versuch..."
        sleep 0.25
    done

    if [ "$bootstrap_ok" -ne 1 ]; then
        echo "ERROR: Image LaunchAgent konnte nicht geladen werden."
        return 1
    fi

    if ! wait_image_ready; then
        launchctl print "$LAUNCHD_DOMAIN/$IMAGE_LABEL" 2>&1 || true
        tail -n 80 "$HOME/.config/mlx-web/image-error.log" 2>/dev/null || true
        return 1
    fi

    echo "Image-Service wurde erfolgreich wiederhergestellt."
}

reload_agent_launchagent() {
    if [ ! -f "$AGENT_PLIST" ]; then
        echo "ERROR: Agent LaunchAgent fehlt: $AGENT_PLIST"
        return 1
    fi

    echo "Agent LaunchAgent wird neu geladen..."

    if launchctl print "$LAUNCHD_DOMAIN/$AGENT_LABEL" >/dev/null 2>&1; then
        launchctl bootout "$LAUNCHD_DOMAIN/$AGENT_LABEL" || true
    fi

    wait_agent_unloaded || return 1

    local attempt
    local bootstrap_ok=0
    for attempt in $(seq 1 20); do
        if launchctl bootstrap "$LAUNCHD_DOMAIN" "$AGENT_PLIST"; then
            bootstrap_ok=1
            break
        fi
        echo "Agent bootstrap Versuch $attempt fehlgeschlagen; neuer Versuch..."
        sleep 0.25
    done

    if [ "$bootstrap_ok" -ne 1 ]; then
        echo "ERROR: Agent LaunchAgent konnte nicht geladen werden."
        return 1
    fi

    if ! wait_agent_ready; then
        launchctl print "$LAUNCHD_DOMAIN/$AGENT_LABEL" 2>&1 || true
        return 1
    fi

    echo "Agent LaunchAgent ist wieder bereit."
}

echo
echo "============================================================"
echo "MLX NOBBY — RESTART ALL"
echo "$(date)"
echo "============================================================"

cd "$PROJECT_DIR"
export MLX_NOBBY_BUILD_SHA="$(git -C "$PROJECT_DIR" rev-parse --short=12 HEAD 2>/dev/null || printf 'unknown')"

if [ ! -x "$MLX_BIN" ]; then
    MLX_BIN="$(command -v mlx || true)"
fi

if [ -z "$MLX_BIN" ] || [ ! -x "$MLX_BIN" ]; then
    echo "ERROR: mlx executable not found"
    exit 127
fi

echo "mlx: $MLX_BIN"
echo "revision: $MLX_NOBBY_BUILD_SHA"

# Let the initiating HTTP response leave the agent before restarting it.
sleep 1

echo
echo "===== REBUILD FRONTEND ====="

report_lifecycle \
    "running" \
    "rebuild-frontend" \
    1 \
    3 \
    "Frontend wird neu gebaut."

docker compose up -d --build --force-recreate mlx-web

echo
echo "===== SYNC LAUNCHAGENTS ====="

if [ -x "$PROJECT_DIR/scripts/install-launchd.sh" ]; then
    "$PROJECT_DIR/scripts/install-launchd.sh"
elif [ -f "$PROJECT_DIR/scripts/install-launchd.sh" ]; then
    bash "$PROJECT_DIR/scripts/install-launchd.sh"
fi

# `mlx restart-all` intentionally keeps an already healthy agent alive. Reload
# it explicitly here so route/entrypoint and plist changes are actually picked
# up after a pull/rebuild. Waiting for launchd to fully remove the previous job
# avoids leaving the agent offline when bootstrap races with bootout.
reload_agent_launchagent

echo
echo "===== RESTART SERVICES ====="

report_lifecycle \
    "running" \
    "restart-services" \
    2 \
    3 \
    "MLX-Dienste werden neu gestartet."

# Keep going long enough to repair the image LaunchAgent even when the inner
# service manager exits non-zero. The original failure is still propagated
# after the recovery attempt so unrelated restart failures never get hidden.
set +e
"$MLX_BIN" restart-all
restart_status=$?
set -e

image_recovery_status=0
ensure_image_launchagent_ready || image_recovery_status=$?

if [ "$image_recovery_status" -ne 0 ]; then
    report_lifecycle \
        "failed" \
        "restart-services" \
        2 \
        3 \
        "Image-Service konnte nach dem Neustart nicht wiederhergestellt werden." \
        "image service unavailable on port 8030"
    exit "$image_recovery_status"
fi

if [ "$restart_status" -ne 0 ]; then
    report_lifecycle \
        "failed" \
        "restart-services" \
        2 \
        3 \
        "MLX-Dienste meldeten beim Neustart einen Fehler; Image-Service wurde dennoch wiederhergestellt." \
        "mlx restart-all exited with status $restart_status"
    exit "$restart_status"
fi

report_lifecycle \
    "completed" \
    "completed" \
    3 \
    3 \
    "Frontend und alle MLX-Dienste wurden neu gestartet."

echo
echo "===== COMPLETE ====="
echo "$(date)"
