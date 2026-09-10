#!/bin/bash

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

OK=0
WARN=0
FAIL=0

green='\033[0;32m'
yellow='\033[0;33m'
red='\033[0;31m'
bold='\033[1m'
reset='\033[0m'

ok() {
    printf "${green}✓${reset} %s\n" "$1"
    OK=$((OK + 1))
}

warn() {
    printf "${yellow}!${reset} %s\n" "$1"
    WARN=$((WARN + 1))
}

fail() {
    printf "${red}✗${reset} %s\n" "$1"
    FAIL=$((FAIL + 1))
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

check_port() {
    local port="$1"
    local name="$2"

    if curl -fsS --max-time 2 "http://127.0.0.1:${port}/" >/dev/null 2>&1; then
        ok "$name erreichbar auf Port $port"
    elif lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        ok "$name lauscht auf Port $port"
    else
        warn "$name nicht erreichbar auf Port $port"
    fi
}

printf "\n${bold}MLX nobby Doctor${reset}\n"
printf "Lokale System- und Runtime-Diagnose\n\n"

if [ "$(uname -s)" = "Darwin" ]; then
    ok "macOS erkannt"
else
    fail "MLX nobby benötigt macOS"
fi

ARCH="$(uname -m)"
if [ "$ARCH" = "arm64" ]; then
    ok "Apple Silicon erkannt ($ARCH)"
else
    fail "Apple Silicon nicht erkannt ($ARCH)"
fi

MACOS_VERSION="$(sw_vers -productVersion 2>/dev/null || true)"
if [ -n "$MACOS_VERSION" ]; then
    ok "macOS $MACOS_VERSION"
fi

MEMORY_BYTES="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
if [ "$MEMORY_BYTES" -gt 0 ]; then
    MEMORY_GB=$((MEMORY_BYTES / 1024 / 1024 / 1024))

    if [ "$MEMORY_GB" -ge 32 ]; then
        ok "${MEMORY_GB} GB Unified Memory"
    elif [ "$MEMORY_GB" -ge 16 ]; then
        warn "${MEMORY_GB} GB Unified Memory – große Modelle sind eingeschränkt"
    else
        fail "${MEMORY_GB} GB RAM – für MLX nobby zu wenig"
    fi
fi

printf "\n${bold}Werkzeuge${reset}\n"

if command_exists git; then
    ok "Git: $(git --version)"
else
    fail "Git fehlt"
fi

if command_exists python3; then
    ok "Python: $(python3 --version 2>&1)"
else
    fail "Python 3 fehlt"
fi

if command_exists docker; then
    ok "Docker CLI: $(docker --version)"
else
    fail "Docker fehlt"
fi

if command_exists docker && docker info >/dev/null 2>&1; then
    ok "Docker Engine läuft"
else
    fail "Docker Engine läuft nicht"
fi

if command_exists ffmpeg; then
    ok "FFmpeg: $(ffmpeg -version 2>/dev/null | head -1)"
else
    warn "FFmpeg nicht gefunden"
fi

printf "\n${bold}Python-Umgebungen${reset}\n"

for venv in agent-venv runtime-venv embedding-venv image-venv speech-venv; do
    if [ -x "$ROOT/$venv/bin/python" ]; then
        version="$("$ROOT/$venv/bin/python" --version 2>&1)"
        ok "$venv: $version"
    else
        warn "$venv fehlt"
    fi
done

printf "\n${bold}MLX nobby Services${reset}\n"

check_port 8000 "MLX Runtime"
check_port 8010 "Agent"
check_port 8020 "Embeddings"
check_port 8030 "Images"
check_port 8040 "Router"
check_port 8050 "Speech"
check_port 8090 "Web"

printf "\n${bold}Docker${reset}\n"

if command_exists docker && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'mlx-web'; then
    ok "Container mlx-web läuft"
else
    warn "Container mlx-web läuft nicht"
fi

printf "\n${bold}Modelle${reset}\n"

MODEL_ROOT="${HOME}/Models"

if [ -d "$MODEL_ROOT" ]; then
    MODEL_COUNT="$(find "$MODEL_ROOT" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')"

    if [ "$MODEL_COUNT" -gt 0 ]; then
        ok "$MODEL_COUNT Modell-Verzeichnisse in ~/Models gefunden"
    else
        warn "~/Models existiert, enthält aber keine Modell-Verzeichnisse"
    fi
else
    warn "~/Models existiert nicht"
fi

printf "\n${bold}Ergebnis${reset}\n"
printf "${green}%s OK${reset} · ${yellow}%s Warnungen${reset} · ${red}%s Fehler${reset}\n\n" "$OK" "$WARN" "$FAIL"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi

exit 0
