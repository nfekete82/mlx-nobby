#!/bin/bash
# Install ONLY the optional 4B-memory supervisor. Never restart unrelated AI.
set -euo pipefail
ROOT="$HOME/mlx-web"
LABEL="de.nobby.mlx-memory-supervisor"
DOMAIN="gui/$(id -u)"
TEMPLATE="$ROOT/launchd/templates/$LABEL.plist.template"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
CONFIG="$HOME/.config/mlx-web"

test -x "$ROOT/runtime-venv/bin/python" || { echo "Missing MLX runtime Python"; exit 1; }
test -f "$HOME/Models/router/Qwen3.5-4B-MLX-4bit/config.json" || { echo "Missing local 4B model"; exit 1; }
test -f "$TEMPLATE" || { echo "Missing LaunchAgent template"; exit 1; }

if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 &&
   lsof -nP -iTCP:8011 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port 8011 is used by a manually started server."
    echo "Stop that server with Ctrl-C in its own terminal, then rerun this installer."
    echo "No service or production model was stopped."
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$CONFIG"
chmod 700 "$CONFIG"
CANDIDATE="$(mktemp "$HOME/Library/LaunchAgents/.$LABEL.XXXXXXXX.plist")"
trap 'rm -f "$CANDIDATE"' EXIT
sed -e "s|__PROJECT_DIR__|$ROOT|g" \
    -e "s|__CONFIG_DIR__|$CONFIG|g" "$TEMPLATE" >"$CANDIDATE"
plutil -lint "$CANDIDATE" >/dev/null
"$ROOT/runtime-venv/bin/python" "$ROOT/scripts/reload-launchagent.py" \
    "$DOMAIN" "$LABEL" "$CANDIDATE" "$TARGET"

if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    launchctl bootstrap "$DOMAIN" "$TARGET"
fi
echo "Supervisor installed. No other MLX services restarted."
echo "Status: $CONFIG/memory-model-control/state.json"
echo "Check: launchctl print $DOMAIN/$LABEL"
