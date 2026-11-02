#!/usr/bin/env bash
# Safe, non-destructive source update for the local MLX Nobby checkout.
# This script intentionally never stops services, deletes files, or changes models.
set -euo pipefail

TARGET_BRANCH="feat/mlx-local-integration-20261102"
ACTION="check"

usage() {
    cat <<'USAGE'
Usage: bash scripts/local-update.sh [--check | --apply]

--check   Fetch integration branch and validate fast-forward safety (default).
--apply   Switch to the integration branch and fast-forward it.
          Existing untracked files are NOT deleted.
          Running services are NOT restarted.
USAGE
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --check) ACTION="check" ;;
        --apply) ACTION="apply" ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
info() { printf '%s\n' "$*"; }

for cmd in git; do
    command -v "$cmd" >/dev/null 2>&1 || die "$cmd is required"
done
[ "$(git rev-parse --is-inside-work-tree 2>/dev/null)" = "true" ] || die "Not a Git checkout"
[ -n "$(git remote get-url origin 2>/dev/null)" ] || die "Missing origin remote"

info "MLX Nobby safe local update"
info "Repository: $ROOT"
info "Target: $TARGET_BRANCH"
info "Current branch: $(git branch --show-current)"

# Fetch only the target ref. Do not modify any checked-out files in --check.
git fetch --no-tags origin "refs/heads/$TARGET_BRANCH:refs/remotes/origin/$TARGET_BRANCH"
remote_ref="refs/remotes/origin/$TARGET_BRANCH"
remote_sha="$(git rev-parse --verify "$remote_ref")"

if git show-ref --verify --quiet "refs/heads/$TARGET_BRANCH"; then
    local_sha="$(git rev-parse "refs/heads/$TARGET_BRANCH")"
    if ! git merge-base --is-ancestor "$local_sha" "$remote_sha"; then
        die "Local integration branch diverges from origin; nothing was overwritten."
    fi
fi

changed="$(git status --porcelain --untracked-files=no)"
untracked_count="$(git ls-files --others --exclude-standard | wc -l | tr -d ' ')"
if [ -n "$changed" ]; then
    info "Tracked local changes detected (left untouched):"
    git status --short --untracked-files=no
    [ "$ACTION" != "apply" ] || die "Commit/stash tracked changes manually before --apply."
fi
if [ "$untracked_count" -gt 0 ]; then
    info "Notice: $untracked_count untracked files are present; they will NOT be deleted."
fi

if [ "$ACTION" = "check" ]; then
    info "Remote revision: $remote_sha"
    info "Preflight completed. Run 'bash scripts/local-update.sh --apply' to switch."
    exit 0
fi

# Some Python imports happen at job time, so refuse to replace source files
# while a render is active. A running service with unreadable health is unsafe.
for cmd in curl lsof python3; do
    command -v "$cmd" >/dev/null 2>&1 || die "$cmd is required for --apply"
done
for entry in "8030:Images" "8060:Video"; do
    port="$(printf '%s' "$entry" | cut -d: -f1)"
    service="$(printf '%s' "$entry" | cut -d: -f2)"
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        payload="$(curl -fsS --max-time 5 "http://127.0.0.1:$port/health")" \
            || die "$service is running but health cannot be read; retry after jobs finish."
        printf '%s' "$payload" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except (ValueError, TypeError):
    sys.exit("Unparseable media health payload")
if not isinstance(data, dict):
    sys.exit("Unexpected health structure")
status = str(data.get("status") or "").lower()
active = data.get("active_generation") is True or bool(data.get("active_job_id"))
active = active or status in ("busy", "running", "generating", "processing")
if active:
    sys.exit("Media generation is active; update aborted")
' || die "$service has an active or unknown workload; no source files changed."
    fi
done

if git show-ref --verify --quiet "refs/heads/$TARGET_BRANCH"; then
    git switch "$TARGET_BRANCH"
else
    git switch --track -c "$TARGET_BRANCH" "origin/$TARGET_BRANCH"
fi
git merge --ff-only "$remote_ref"
[ "$(git rev-parse HEAD)" = "$remote_sha" ] || die "Unexpected local HEAD after fast-forward"

info "Code updated to: $(git rev-parse --short=12 HEAD)"
info "No local models, media, configurations, Docker volumes or services were changed."
info "Restart services only when no image/video/chat job is running."
