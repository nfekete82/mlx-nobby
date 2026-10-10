#!/usr/bin/env bash
# Fast CPU-only checks, never starting Docker or native MLX services.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="${MLX_TEST_PYTHON:-$ROOT/test-venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then PYTHON=python3; fi
tier="${1:-}"
shift || true
case "$tier" in
  quick)
    if [[ "$#" -eq 0 ]]; then
      echo "Usage: mlx test-quick <pytest paths or -k expression>"
      echo "Example: mlx test-quick tests/test_intent_aware_chart_routing.py"
      exit 2
    fi
    exec "$PYTHON" -m pytest -q "$@"
    ;;
  medium)
    if [[ "$#" -gt 0 ]]; then
      echo "test-medium accepts no additional arguments" >&2
      exit 2
    fi
    "$PYTHON" -m pytest -q
    node --test tests/*.mjs
    ;;
  *)
    echo "Unknown test tier: $tier" >&2
    exit 2
    ;;
esac
