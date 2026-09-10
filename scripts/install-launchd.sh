#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOME_DIR="${HOME}"
CONFIG_DIR="${HOME}/.config/mlx-web"
RUNTIME_PYTHON="${MLX_RUNTIME_PYTHON:-${PROJECT_DIR}/runtime-venv/bin/python}"
ROUTER_MODEL="${MLX_ROUTER_MODEL_PATH:-${HOME}/Models/router/Qwen3.5-0.8B-MLX-4bit}"
TEMPLATE_DIR="${PROJECT_DIR}/launchd/templates"
TARGET_DIR="${HOME}/Library/LaunchAgents"

mkdir -p "${CONFIG_DIR}"
mkdir -p "${TARGET_DIR}"

if [ ! -x "${RUNTIME_PYTHON}" ]; then
    echo "Fehler: NobbyMLX Runtime fehlt: ${RUNTIME_PYTHON}" >&2
    echo "Installiere zuerst runtime-venv." >&2
    exit 1
fi

if [ ! -x "${PROJECT_DIR}/agent-venv/bin/python" ]; then
    echo "Fehler: agent-venv fehlt." >&2
    exit 1
fi

if [ ! -x "${PROJECT_DIR}/speech-venv/bin/python" ]; then
    echo "Fehler: speech-venv fehlt." >&2
    exit 1
fi

if [ ! -d "${ROUTER_MODEL}" ]; then
    echo "Fehler: Router-Modell fehlt: ${ROUTER_MODEL}" >&2
    exit 1
fi

if [ ! -d "${TEMPLATE_DIR}" ]; then
    echo "Fehler: LaunchAgent-Templates nicht gefunden: ${TEMPLATE_DIR}" >&2
    exit 1
fi

render_template() {
    local source="$1"
    local target="$2"

    sed \
        -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
        -e "s|__CONFIG_DIR__|${CONFIG_DIR}|g" \
        -e "s|__HOME__|${HOME_DIR}|g" \
        -e "s|__RUNTIME_PYTHON__|${RUNTIME_PYTHON}|g" \
        -e "s|__ROUTER_MODEL__|${ROUTER_MODEL}|g" \
        "${source}" > "${target}"

    plutil -lint "${target}" >/dev/null
}

for template in "${TEMPLATE_DIR}"/*.plist.template; do
    [ -e "${template}" ] || continue

    filename="$(basename "${template}" .template)"
    target="${TARGET_DIR}/${filename}"

    render_template "${template}" "${target}"
    echo "Installiert: ${target}"
done

echo
echo "LaunchAgent-Dateien erfolgreich installiert."
echo "Projekt: ${PROJECT_DIR}"
echo "Konfiguration: ${CONFIG_DIR}"
