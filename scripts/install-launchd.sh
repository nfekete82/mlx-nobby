#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOME_DIR="${HOME}"
CONFIG_DIR="${HOME}/.config/mlx-web"
RUNTIME_PYTHON="${MLX_RUNTIME_PYTHON:-${PROJECT_DIR}/runtime-venv/bin/python}"
ROUTER_MODEL="${MLX_ROUTER_MODEL_PATH:-${HOME}/Models/router/Qwen3.5-4B-MLX-4bit}"
MLX_SERVE_DIR="${MLX_SERVE_DIR:-${HOME}/mlx-serve-qwen21}"
MLX_SERVE_BIN="${MLX_SERVE_BIN:-${MLX_SERVE_DIR}/zig-out/bin/mlx-serve}"
TEMPLATE_DIR="${PROJECT_DIR}/launchd/templates"
TARGET_DIR="${HOME}/Library/LaunchAgents"
LAUNCHD_DOMAIN="gui/$(id -u)"

mkdir -p "${CONFIG_DIR}"
mkdir -p "${TARGET_DIR}"

if [ ! -x "${RUNTIME_PYTHON}" ]; then
    echo "Error: MLX Nobby runtime is missing: ${RUNTIME_PYTHON}" >&2
    echo "Install runtime-venv first." >&2
    exit 1
fi

for environment in agent-venv embedding-venv image-venv speech-venv; do
    if [ ! -x "${PROJECT_DIR}/${environment}/bin/python" ]; then
        echo "Error: ${environment} is missing." >&2
        exit 1
    fi
done

if [ ! -d "${ROUTER_MODEL}" ]; then
    echo "Error: router model is missing: ${ROUTER_MODEL}" >&2
    exit 1
fi

if [ ! -d "${TEMPLATE_DIR}" ]; then
    echo "Error: LaunchAgent templates not found: ${TEMPLATE_DIR}" >&2
    exit 1
fi

render_template() {
    local source="$1"
    local target="$2"
    local temporary="${target}.tmp.$$"

    sed \
        -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
        -e "s|__CONFIG_DIR__|${CONFIG_DIR}|g" \
        -e "s|__HOME_DIR__|${HOME}|g" \
        -e "s|__HOME__|${HOME_DIR}|g" \
        -e "s|__RUNTIME_PYTHON__|${RUNTIME_PYTHON}|g" \
        -e "s|__ROUTER_MODEL__|${ROUTER_MODEL}|g" \
        -e "s|__MLX_SERVE_DIR__|${MLX_SERVE_DIR}|g" \
        -e "s|__MLX_SERVE_BIN__|${MLX_SERVE_BIN}|g" \
        "${source}" > "${temporary}"

    if [ "$(basename "${source}")" = "de.nobby.mlx-video.plist.template" ]; then
        "${RUNTIME_PYTHON}" - "${temporary}" "${target}" <<'PY'
import os
import plistlib
import sys

path = sys.argv[1]
with open(path, "rb") as handle:
    data = plistlib.load(handle)
previous = {}
if len(sys.argv) > 2 and os.path.isfile(sys.argv[2]):
    with open(sys.argv[2], "rb") as handle:
        previous = plistlib.load(handle).get("EnvironmentVariables", {})
for name in ("LTX_MLX_UNCENSORED_LORA", "LTX_MLX_UNCENSORED_LORA_STRENGTH"):
    if name in os.environ:
        data["EnvironmentVariables"][name] = os.environ[name]
    elif name in previous:
        data["EnvironmentVariables"][name] = previous[name]
with open(path, "wb") as handle:
    plistlib.dump(data, handle, sort_keys=False)
PY
    fi

    if [ "$(basename "${source}")" = "de.nobby.mlx-speech.plist.template" ]; then
        "${RUNTIME_PYTHON}" - "${temporary}" "${target}" <<'PY'
import os
import plistlib
import sys

path = sys.argv[1]
with open(path, "rb") as handle:
    data = plistlib.load(handle)
previous = {}
if len(sys.argv) > 2 and os.path.isfile(sys.argv[2]):
    with open(sys.argv[2], "rb") as handle:
        previous = plistlib.load(handle).get("EnvironmentVariables", {})
environment = data.setdefault("EnvironmentVariables", {})
for name in ("MLX_SPEECH_MODEL",):
    if name in os.environ:
        environment[name] = os.environ[name]
    elif name in previous:
        environment[name] = previous[name]
if not environment:
    data.pop("EnvironmentVariables", None)
with open(path, "wb") as handle:
    plistlib.dump(data, handle, sort_keys=False)
PY
    fi

    plutil -lint "${temporary}" >/dev/null

    "${RUNTIME_PYTHON}" "${SCRIPT_DIR}/reload-launchagent.py" \
        "${LAUNCHD_DOMAIN}" "$(basename "${target}" .plist)" "${temporary}" "${target}"
}

for template in "${TEMPLATE_DIR}"/*.plist.template; do
    [ -e "${template}" ] || continue

    filename="$(basename "${template}" .template)"
    target="${TARGET_DIR}/${filename}"

    if [ "${filename}" = "de.nobby.mlx-serve.plist" ] && [ ! -x "${MLX_SERVE_BIN}" ]; then
        echo "Skipping: ${filename} (mlx-serve binary not found: ${MLX_SERVE_BIN})"
        continue
    fi

    render_template "${template}" "${target}"
done

echo
echo "LaunchAgent files installed successfully."
echo "Project: ${PROJECT_DIR}"
echo "Configuration: ${CONFIG_DIR}"
