#!/bin/bash

set -Eeuo pipefail

PROJECT_DIR="${MLX_NOBBY_PROJECT_DIR:-$HOME/mlx-web}"
if [ "${MLX_LIFECYCLE_LOCKED:-0}" != "1" ]; then
    exec python3 "$PROJECT_DIR/scripts/ai-lifecycle.py" run "$0" "$@"
fi
LOG_FILE="${MLX_NOBBY_REBOOT_LOG:-/tmp/mlx-nobby-rebuild.log}"

export PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/Applications/OrbStack.app/Contents/MacOS/xbin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

MLX_BIN="${MLX_BIN:-$HOME/bin/mlx}"
DOCKER_BIN="${DOCKER_BIN:-$(command -v docker || true)}"

exec >>"$LOG_FILE" 2>&1

ACTION="reboot"
export MLX_LIFECYCLE_HOLD=1

AGENT_URL="${MLX_NOBBY_AGENT_URL:-http://127.0.0.1:8010}"
PORT_CHECK_BIN="${PORT_CHECK_BIN:-$(command -v lsof || true)}"
HTTP_CHECK_BIN="${MLX_NOBBY_HTTP_CHECK_BIN:-$(command -v curl || true)}"
INSTALL_LAUNCHD_BIN="${MLX_NOBBY_INSTALL_LAUNCHD_BIN:-$PROJECT_DIR/scripts/install-launchd.sh}"
WEB_URL="${MLX_NOBBY_WEB_URL:-http://127.0.0.1:8090}"
SERVICE_WAIT_TIMEOUT="${MLX_NOBBY_SERVICE_WAIT_TIMEOUT:-60}"
EXPECTED_PORTS="${MLX_NOBBY_REBOOT_PORTS:-8000 8010 8020 8030 8040 8050 8060 8090 11234}"
LIFECYCLE_REPORT_FILE="${MLX_NOBBY_LIFECYCLE_REPORT_FILE:-}"
CURRENT_STEP=0
TOTAL_STEPS=7
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

wait_for_http() {
    local url="$1"
    local attempts=$((SERVICE_WAIT_TIMEOUT * 2))
    local attempt

    for ((attempt = 1; attempt <= attempts; attempt++)); do
        if "$HTTP_CHECK_BIN" -fsS --connect-timeout 1 --max-time 3 "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.5
    done

    FAILURE_DETAIL="HTTP-Endpunkt $url ist nach ${SERVICE_WAIT_TIMEOUT}s nicht bereit."
    echo "ERROR: $FAILURE_DETAIL"
    return 1
}

verify_web_api() {
    local version_json status_json expected_version
    expected_version="$(tr -d '\r\n' < "$PROJECT_DIR/VERSION")"
    version_json="$("$HTTP_CHECK_BIN" -fsS --connect-timeout 1 --max-time 3 "$WEB_URL/api/version")" || {
        FAILURE_DETAIL="Version API ist nicht erreichbar."
        return 1
    }

    if ! python3 - "$MLX_NOBBY_BUILD_SHA" "$expected_version" "$version_json" <<'PYVERIFY'
import json
import sys
expected_sha, expected_version, value = sys.argv[1:]
try:
    actual = json.loads(value)
except (ValueError, TypeError):
    sys.exit(1)
sys.exit(0 if (
    isinstance(actual, dict)
    and actual.get("commit") == expected_sha
    and actual.get("version") == expected_version
) else 1)
PYVERIFY
    then
        FAILURE_DETAIL="Web-Version oder Commit stimmt nicht mit dem ausgecheckten Code überein."
        echo "ERROR: $FAILURE_DETAIL"
        return 1
    fi

    status_json="$("$HTTP_CHECK_BIN" -fsS --connect-timeout 1 --max-time 3 "$WEB_URL/api/mlx/status")" || {
        FAILURE_DETAIL="Web-Agent-Proxy antwortet nicht."
        return 1
    }
    if ! python3 - "$status_json" <<'PYSTATUS'
import json
import sys
try:
    status = json.loads(sys.argv[1])
except (TypeError, ValueError):
    sys.exit(1)
sys.exit(0 if isinstance(status, dict) and status.get("online") is True else 1)
PYSTATUS
    then
        FAILURE_DETAIL="Web-Agent-Proxy meldet keinen betriebsbereiten Modellserver."
        echo "ERROR: $FAILURE_DETAIL"
        return 1
    fi

    echo "Web-Version, Commit und Chat-Proxy verifiziert: $expected_version / $MLX_NOBBY_BUILD_SHA"
}

sync_source() {
    if [ "${MLX_NOBBY_SKIP_SOURCE_SYNC:-0}" = "1" ]; then
        echo "Source sync für isolierte Prüfung deaktiviert."
        return 0
    fi

    local branch
    branch="$(git -C "$PROJECT_DIR" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"

    if [ "$branch" != "main" ]; then
        echo "Source sync übersprungen: aktiver Branch ist '${branch:-detached HEAD}', nicht main."
        return 0
    fi

    if [ -n "$(git -C "$PROJECT_DIR" status --porcelain --untracked-files=no)" ]; then
        echo "Source sync übersprungen: Änderungen an getrackten Dateien vorhanden."
        return 0
    fi

    if ! git -C "$PROJECT_DIR" remote get-url origin >/dev/null 2>&1; then
        echo "Source sync übersprungen: origin ist nicht konfiguriert."
        return 0
    fi

    echo "Hole aktuellen Stand von origin/main ..."
    if ! git -C "$PROJECT_DIR" fetch origin main; then
        echo "WARN: origin/main konnte nicht geladen werden; lokaler Stand wird weiter verwendet."
        return 0
    fi

    if ! git -C "$PROJECT_DIR" merge --ff-only origin/main; then
        echo "WARN: Fast-Forward nicht möglich (z.B. Konflikt mit ungetrackter Datei); lokaler Stand und Benutzerdateien bleiben erhalten."
        return 0
    fi
}

verify_web_revision() {
    local built_revision
    built_revision="$(
        "$DOCKER_BIN" compose exec -T mlx-web \
            sh -c 'cat /app/.mlx-nobby-build-revision 2>/dev/null' \
            | tr -d '\r\n'
    )"

    if [ "$built_revision" != "$MLX_NOBBY_BUILD_SHA" ]; then
        FAILURE_DETAIL="Web-Image ist nicht auf Revision ${MLX_NOBBY_BUILD_SHA} gebaut (gefunden: ${built_revision:-unbekannt})."
        echo "ERROR: $FAILURE_DETAIL"
        return 1
    fi

    echo "Web-Image revision verified: $built_revision"
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

echo "mlx:      $MLX_BIN"
echo "docker:   $DOCKER_BIN"
echo "revision: wird nach sicherer Git-Synchronisierung ermittelt"

if [ -z "$PORT_CHECK_BIN" ] || [ ! -x "$PORT_CHECK_BIN" ]; then
    echo "ERROR: lsof executable not found"
    exit 127
fi

if [ -z "$HTTP_CHECK_BIN" ] || [ ! -x "$HTTP_CHECK_BIN" ]; then
    echo "ERROR: curl executable not found"
    exit 127
fi

if [ ! -x "$INSTALL_LAUNCHD_BIN" ]; then
    echo "ERROR: LaunchAgent installer not executable: $INSTALL_LAUNCHD_BIN"
    exit 127
fi

# Let the initiating HTTP response finish first.
sleep 1

echo
echo "===== STOP AI SERVICES ====="

FAILED_PHASE="stop-ai"
FAILURE_DETAIL="mlx stop-ai ist fehlgeschlagen."
CURRENT_STEP=1
report_lifecycle \
    "running" \
    "$FAILED_PHASE" \
    "$CURRENT_STEP" \
    "$TOTAL_STEPS" \
    "KI-Dienste werden sauber beendet; Agent und Control-Prozess bleiben aktiv."

"$MLX_BIN" stop-ai
AI_STOPPED=1

FAILED_PHASE="sync-source"
FAILURE_DETAIL=""
CURRENT_STEP=0
report_lifecycle \
    "running" \
    "$FAILED_PHASE" \
    "$CURRENT_STEP" \
    "$TOTAL_STEPS" \
    "Aktueller main-Stand wird, wenn sicher möglich, von GitHub geladen."

sync_source

export MLX_NOBBY_BUILD_SHA="$(git -C "$PROJECT_DIR" rev-parse --short=12 HEAD 2>/dev/null || printf 'unknown')"


echo
echo "===== BUILD WEB + FRONTEND IMAGE ====="

FAILED_PHASE="build-web"
FAILURE_DETAIL="docker compose build mlx-web ist fehlgeschlagen."
CURRENT_STEP=2
report_lifecycle \
    "running" \
    "$FAILED_PHASE" \
    "$CURRENT_STEP" \
    "$TOTAL_STEPS" \
    "Web-Image inklusive aktuellem Frontend wird neu gebaut."

"$DOCKER_BIN" compose build \
    --build-arg "MLX_NOBBY_BUILD_SHA=$MLX_NOBBY_BUILD_SHA" \
    mlx-web

echo
echo "===== FORCE RECREATE WEB ====="

FAILED_PHASE="recreate-web"
FAILURE_DETAIL="docker compose up --force-recreate mlx-web ist fehlgeschlagen."
CURRENT_STEP=3
report_lifecycle \
    "running" \
    "$FAILED_PHASE" \
    "$CURRENT_STEP" \
    "$TOTAL_STEPS" \
    "Web-Anwendung wird mit dem frisch gebauten Frontend neu erstellt."

"$DOCKER_BIN" compose up -d \
    --force-recreate \
    --no-deps \
    mlx-web

verify_web_revision

echo
echo "===== RELOAD UPDATED AGENT ====="

FAILED_PHASE="reload-agent"
FAILURE_DETAIL="Aktualisierte LaunchAgents oder Agent-Code konnten nicht neu geladen werden."
CURRENT_STEP=4
report_lifecycle \
    "running" \
    "$FAILED_PHASE" \
    "$CURRENT_STEP" \
    "$TOTAL_STEPS" \
    "LaunchAgents werden synchronisiert; der Agent wird anschließend neu gestartet."

"$INSTALL_LAUNCHD_BIN"
"$MLX_BIN" agent restart

# The helper is detached: restarting the host Agent resets its in-memory
# lifecycle state but must not terminate this script. Report again when ready.
wait_for_http "$AGENT_URL/api/status"
report_lifecycle \
    "running" \
    "$FAILED_PHASE" \
    "$CURRENT_STEP" \
    "$TOTAL_STEPS" \
    "Neuer Agent ist bereit; der Reboot läuft weiter."

echo
echo "===== RESTART LOCAL SERVICES ====="

FAILED_PHASE="restart-services"
FAILURE_DETAIL="mlx restart-all ist fehlgeschlagen."
CURRENT_STEP=5
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
CURRENT_STEP=6
report_lifecycle \
    "running" \
    "$FAILED_PHASE" \
    "$CURRENT_STEP" \
    "$TOTAL_STEPS" \
    "Erwartete Dienste, APIs und Version werden geprüft."

for port in $EXPECTED_PORTS; do
    wait_for_port "$port"
done

wait_for_http "$AGENT_URL/api/status"
wait_for_http "$WEB_URL/api/version"
wait_for_http "$WEB_URL/api/mlx/status"
verify_web_api

python3 "${MLX_NOBBY_LIFECYCLE_HELPER:-$PROJECT_DIR/scripts/ai-lifecycle.py}" resume
AI_STOPPED=0
report_lifecycle \
    "completed" \
    "completed" \
    "$TOTAL_STEPS" \
    "$TOTAL_STEPS" \
    "MLX Nobby wurde aktualisiert, das Frontend neu gebaut und vollständig gestartet."

echo
echo "===== COMPLETE ====="
echo "$(date)"
