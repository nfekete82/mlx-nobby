#!/bin/bash
set -euo pipefail

# ============================================================
# MLX Nobby Installer
# macOS / Apple Silicon
# ============================================================

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BIN_DIR="$HOME/bin"
CONFIG_DIR="$HOME/.config/mlx-server"
WEB_CONFIG_DIR="$HOME/.config/mlx-web"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"

MLX_SOURCE="$ROOT/scripts/mlx"
MLX_TARGET="$BIN_DIR/mlx"

INSTALL_LAUNCHD="$ROOT/scripts/install-launchd.sh"
DOCTOR="$ROOT/scripts/doctor.sh"

START_WEB=1
INSTALL_LAUNCHD_SERVICES=1


# ------------------------------------------------------------
# Output
# ------------------------------------------------------------

info() {
    printf '\n\033[1;34m%s\033[0m\n' "$*"
}

ok() {
    printf '\033[1;32m✓ %s\033[0m\n' "$*"
}

warn() {
    printf '\033[1;33m⚠ %s\033[0m\n' "$*"
}

fail() {
    printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2
    exit 1
}


# ------------------------------------------------------------
# Arguments
# ------------------------------------------------------------

while [ "$#" -gt 0 ]; do
    case "$1" in
        --no-docker)
            START_WEB=0
            ;;

        --no-launchd)
            INSTALL_LAUNCHD_SERVICES=0
            ;;

        -h|--help)
            cat <<'EOF'

MLX Nobby Installer

Usage:

  ./scripts/install.sh
  ./scripts/install.sh --no-docker
  ./scripts/install.sh --no-launchd

Options:

  --no-docker    Do not build/start the Docker web service
  --no-launchd   Do not install/update macOS LaunchAgents
  -h, --help     Show this help

EOF
            exit 0
            ;;

        *)
            fail "Unknown option: $1"
            ;;
    esac

    shift
done


# ------------------------------------------------------------
# Platform
# ------------------------------------------------------------

info "Checking platform"

if [ "$(uname -s)" != "Darwin" ]; then
    fail "MLX Nobby currently requires macOS."
fi

ARCH="$(uname -m)"

if [ "$ARCH" != "arm64" ]; then
    fail "Apple Silicon is required. Detected architecture: $ARCH"
fi

ok "macOS / Apple Silicon"


# ------------------------------------------------------------
# Repository
# ------------------------------------------------------------

info "Checking repository"

[ -f "$ROOT/docker-compose.yml" ] \
    || fail "docker-compose.yml not found"

[ -f "$MLX_SOURCE" ] \
    || fail "scripts/mlx not found"

[ -f "$DOCTOR" ] \
    || fail "scripts/doctor.sh not found"

ok "Repository: $ROOT"


# ------------------------------------------------------------
# Required tools
# ------------------------------------------------------------

info "Checking required tools"

REQUIRED_COMMANDS=(
    python3
    curl
    launchctl
    lsof
)

MISSING=0

for cmd in "${REQUIRED_COMMANDS[@]}"; do
    if command -v "$cmd" >/dev/null 2>&1; then
        ok "$cmd"
    else
        warn "$cmd not found"
        MISSING=1
    fi
done

if [ "$MISSING" -ne 0 ]; then
    fail "Required tools are missing."
fi


# ------------------------------------------------------------
# Optional tools
# ------------------------------------------------------------

info "Checking optional tools"

if command -v brew >/dev/null 2>&1; then
    ok "Homebrew"
else
    warn "Homebrew not found"
fi

if command -v ffmpeg >/dev/null 2>&1; then
    ok "FFmpeg"
else
    warn "FFmpeg not found – speech/audio conversion may be unavailable"
fi

if command -v docker >/dev/null 2>&1; then
    ok "Docker"
else
    warn "Docker not found – web container cannot be started"
    START_WEB=0
fi


# ------------------------------------------------------------
# Directories
# ------------------------------------------------------------

info "Creating local directories"

mkdir -p \
    "$BIN_DIR" \
    "$CONFIG_DIR" \
    "$WEB_CONFIG_DIR" \
    "$LAUNCHD_DIR"

ok "$BIN_DIR"
ok "$CONFIG_DIR"
ok "$WEB_CONFIG_DIR"
ok "$LAUNCHD_DIR"


# ------------------------------------------------------------
# MLX Manager
# ------------------------------------------------------------

info "Installing MLX Manager"

if [ -f "$MLX_TARGET" ] && cmp -s "$MLX_SOURCE" "$MLX_TARGET"; then
    ok "~/bin/mlx already up to date"
else
    cp "$MLX_SOURCE" "$MLX_TARGET"
    chmod 755 "$MLX_TARGET"
    ok "Installed ~/bin/mlx"
fi


# ------------------------------------------------------------
# PATH hint
# ------------------------------------------------------------

case ":$PATH:" in
    *":$BIN_DIR:"*)
        ok "~/bin is in PATH"
        ;;

    *)
        warn "~/bin is not currently in PATH"

        SHELL_NAME="$(basename "${SHELL:-}")"

        if [ "$SHELL_NAME" = "zsh" ]; then
            warn 'Add this to ~/.zshrc: export PATH="$HOME/bin:$PATH"'
        else
            warn 'Add this to your shell config: export PATH="$HOME/bin:$PATH"'
        fi
        ;;
esac


# ------------------------------------------------------------
# Config
# ------------------------------------------------------------

info "Checking MLX configuration"

if [ -f "$CONFIG_DIR/config" ]; then
    ok "~/.config/mlx-server/config exists"
else
    warn "~/.config/mlx-server/config does not exist yet"
    warn "Configure a model before starting the MLX server."
fi

if [ -f "$CONFIG_DIR/models" ]; then
    ok "~/.config/mlx-server/models exists"
else
    touch "$CONFIG_DIR/models"
    ok "Created empty ~/.config/mlx-server/models"
fi


# ------------------------------------------------------------
# LaunchAgents
# ------------------------------------------------------------

if [ "$INSTALL_LAUNCHD_SERVICES" -eq 1 ]; then

    info "Installing LaunchAgents"

    if [ -x "$INSTALL_LAUNCHD" ]; then
        "$INSTALL_LAUNCHD"
        ok "LaunchAgent installer completed"

    elif [ -f "$INSTALL_LAUNCHD" ]; then
        bash "$INSTALL_LAUNCHD"
        ok "LaunchAgent installer completed"

    else
        warn "scripts/install-launchd.sh not found"
    fi

else
    info "Skipping LaunchAgents"
fi


# ------------------------------------------------------------
# Docker Web
# ------------------------------------------------------------

if [ "$START_WEB" -eq 1 ]; then

    info "Building and starting web service"

    (
        cd "$ROOT"
        docker compose config >/dev/null
        docker compose up -d --build mlx-web
    )

    ok "Web service started"

else
    info "Skipping Docker web service"
fi


# ------------------------------------------------------------
# Doctor
# ------------------------------------------------------------

info "Running system doctor"

if [ -x "$DOCTOR" ]; then
    "$DOCTOR" || warn "Doctor reported one or more warnings"
else
    bash "$DOCTOR" || warn "Doctor reported one or more warnings"
fi


# ------------------------------------------------------------
# Summary
# ------------------------------------------------------------

info "Installation complete"

echo
echo "Useful commands:"
echo
echo "  mlx status"
echo "  mlx services"
echo "  mlx doctor"
echo "  mlx restart"
echo "  mlx restart-all"
echo
echo "Web UI:"
echo
echo "  http://127.0.0.1:8090"
echo

ok "MLX Nobby bootstrap completed"
