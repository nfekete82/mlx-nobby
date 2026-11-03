# MLX Nobby: safe local integration (2026-11-02)

Integration branch: `feat/mlx-local-integration-20261102`.

This branch combines the stable video/manual-media + Escape/gallery fixes,
Strata-inspired benchmarks, guarded Qwen/DFlash2 A/B experiments and the
Ragnarok prompt additions. It is based on
`fix/model-ab-pinned-quality-restore-20261102` and preserves the
removal of automatic Smart Media controls. It does **not** automatically change
models, download checkpoints, alter your runtime configuration or delete media.

## First-time checkout on the Mac

From an existing checkout (typically `~/mlx-web`):

```bash
cd ~/mlx-web
git status --short
git fetch origin feat/mlx-local-integration-20261102
git switch -c feat/mlx-local-integration-20261102 --track origin/feat/mlx-local-integration-20261102
bash scripts/local-update.sh --check
```

If the integration branch already exists locally, replace the `git switch -c`
line with:

```bash
git switch feat/mlx-local-integration-20261102
git merge --ff-only origin/feat/mlx-local-integration-20261102
```

Git refuses to switch when an untracked file conflicts with a tracked file on
the target branch. Do not use `git clean -fd` or `git reset --hard`.
Your untracked LTX experiment files and local model data should remain intact.

## Future updates

```bash
cd ~/mlx-web
bash scripts/local-update.sh --check
bash scripts/local-update.sh --apply
```

The script checks whether the target can fast-forward and stops for tracked
local modifications or active image/video generation. Untracked files remain
untouched. It does **not** restart running processes, install packages, or change
checkpoints.

## Activate changed services (manually, only when jobs are idle)

Code on disk and running processes are separate. The prompt improvements run
in the agent process; the frontend runs in Docker. After the job queue is idle,
run, as appropriate:

```bash
cd ~/mlx-web
mlx agent restart
mlx video restart
export MLX_NOBBY_BUILD_SHA="$(git rev-parse --short=12 HEAD)"
docker compose up -d --build mlx-web
mlx doctor
```

On machines where the image-service or other native service needs a refresh,
use its existing documented `mlx` service management command,
but only when all media jobs are finished. Do not run global restart scripts
during an active image/video job.

## Validation

GitHub Actions provides Python, JS, shell and Docker checks for the branch.
A successful CI result does not replace a real on-device smoke test: verify
Ragnarok preset selection, one simple Juggernaut generation, LTX preview and
manual Extend, the Library Escape behavior, and retained model configuration.

Roll back the code by switching to your previous branch; never remove private
media or venv/model directories. Existing running services may need to be
restarted after that switch when idle.

## Read-only operating health check

The new command combines Git divergence, service readiness, stale native service
revisions and active/waiting job counts. It never prints prompts, file paths,
model paths or individual job IDs, and makes no changes to running services.

```bash
cd ~/mlx-web
python3 scripts/local-health.py
python3 scripts/local-health.py --json     # sanitized output safe to share
python3 scripts/local-health.py --strict   # optional services become required
```

The check uses the local tracking refs without fetching; run `git fetch origin`
first when you need a current upstream comparison. An offline/idle LLM model
runtime is not a failure unless explicitly requested with `--runtime`.
This diagnostic does not replace real on-device LTX/Juggernaut acceptance.
