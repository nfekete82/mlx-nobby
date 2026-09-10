#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOME_DIR="${HOME}"
CONFIG_DIR="${HOME}/.config/mlx-web"
TEMPLATE_DIR="${PROJECT_DIR}/launchd/templates"
TARGET_DIR="${HOME}/Library/LaunchAgents"

mkdir -p "${CONFIG_DIR}"
mkdir -p "${TARGET_DIR}"

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
