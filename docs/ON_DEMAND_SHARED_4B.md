# On-demand shared Qwen 4B router (opt-in)

## Goal and safety boundary

Legacy port 8011 (dedicated memory learning) and port 8040 (semantic router) launch **two independent processes with the exact same local Qwen 4B checkpoint**. On a 48-GB unified-memory Mac, duplicate model residency leaves less headroom for SDXL and LTX.

The gateway is **opt-in**; checking out Git does not stop, alter or reload any running service or private memory. All activation must be reviewed separately.

## Implementation

- Port 8040: a lightweight localhost-only HTTP gateway, with **no model weights**. It provides health, model listing and the non-streaming chat-completion route needed by the semantic router.
- Port 8011: the existing single supervisor-owned 4B, shared between memory extraction and router classification. It wakes only for a real extraction/router demand, then may be released after 120 seconds without demand.
- The gateway never starts a second 4B, downloads weights or logs prompts. Its inference lease and the existing cross-process media runtime lease protect in-flight router and extraction requests.
- Image/video retain priority. The exclusive media handoff rejects a legacy resident router on port 8040 when shared mode is opted in and verifies the gateway carries no model weights.
- The router gateway keeps its tiny health server running; the shared 4B model can be unloaded. A listening port is not proof of resident weights.
- A change to dedicated Memory settings can make the shared router unavailable; the gateway fails closed, and rollback restores the original full router service.

## What is not changed

The 27B chat model is **not** automatically shut down after an idle timeout in this PR. Doing so safely requires end-to-end in-flight tracking for direct web streaming and a guaranteed chat cold-start path; an empty media queue cannot prove that a 27B response is idle.

No change to the 20% free-memory guard, swap growth limit of 0.5 GB per job, model-load reserves, private SQLite retention or memory extraction checkpoints.

## Local check (read-only)

Use a verified private backup and a test worktree. The script has an explicit check mode:

    cd ~/mlx-nobby-on-demand-review
    python3 scripts/switch-shared-4b-router.py --check --backup "$HOME/Backups/mlx-pre-media-20261106-223604"
    python3 -m pytest -q tests/test_on_demand_model_manager.py tests/test_memory_model_supervisor.py tests/test_dedicated_memory_model.py tests/test_exclusive_model_handoff.py

Do not activate while any media, router, chat or memory extraction is running.

## Explicit activation (after production code rollout and real acceptance preflight)

    python3 scripts/switch-shared-4b-router.py --enable --backup "$HOME/Backups/mlx-pre-media-20261106-223604"
    curl -fsS http://127.0.0.1:8040/health

The switcher verifies the private backup, dedicated supervisor, model and idle media state, acquires existing cross-process locks, saves the previous router plist in a private directory, and reloads **only the router LaunchAgent**. The policy file is owner-only, and the regular installer preserves the gateway on subsequent restarts. Never activate it from a review worktree while live services still import old source files.

Safe rollback when idle:

    python3 scripts/switch-shared-4b-router.py --rollback

Do not kill unmanaged processes, wipe the swap, delete memories, reset chat databases, or raise guard thresholds to bypass a failed admission.

## Real acceptance still needed

Synthetic tests do not demonstrate physical Metal/MLX memory reclamation. On the target Mac, separately exercise real router classification, memory extraction, one Juggernaut XL Ultra+ image, one LTX video, and chat restoration. Compare model server PIDs, loaded indicators, macOS free memory, peak swap delta per job and completed artifact state.
