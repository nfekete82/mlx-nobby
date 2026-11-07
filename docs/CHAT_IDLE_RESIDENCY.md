# Qwen 27B chat model idle residency (opt-in, not deployed)

## Evidence and motivation

On the target 48-GB Mac, Qwen 27B with DFlash2 on port 8000 stayed resident for nearly 8 hours with the web UI closed. The user's `vmmap` reported ~18.9 GB resident for that process; macOS also reported 55% free memory and ~9.75 GB existing swap. This alone does **not** prove a leak or active low-memory pressure.

The shared Qwen 4B gateway (8040 -> supervisor-owned 8011) does **not** manage the independent Qwen 27B on port 8000. The installed MLX-VLM reports `POST /unload`, `GET /metrics`, `GET /health`. The user-provided schema includes `summary.requests_started`, `summary.in_flight`, `summary.last_request_at`, `server.loaded_model`, and `server.request_queue_depth`.

## Implementation and defaults

`python3 scripts/chat-idle-manager.py --check` is read-only and performs three local, content-free probes. `--watch` **without** `--apply` only observes; it will not unload. Nothing is launched or installed by checking out this PR.

`--watch --apply` is explicit opt-in. It unloads after 600 seconds of **continuously observed** idle state, checked every 30 seconds (the initial ten-minute grace starts when the watchdog begins observing, not when the browser closes).

- Require healthy port 8000 and explicit, mutually consistent `loaded_model` fields in health and metrics. Refuse ambiguous or multiple-model residency.
- Require authoritative nonnegative integer `requests_started`, `in_flight`, `request_queue_depth`, and native Agent `active_agent_runs`; an error or missing field resets the idle timer.
- Reset on new user request, active inference, queued request, Agent run, model switch, or loss of metrics. The last-request marker is used for **change detection**, not assumed to use any particular clock unit.
- Acquire the shared `runtime_coordinator.runtime_lease` for the actual unload attempt; coordinated chat, tools, model switches and media must finish first.
- Re-probe twice under the lease and verify no new requests and the same loaded model; call `POST /unload` exactly once, then confirm `/health.loaded_model` is null. No process kill or launchctl restart.
- Log only non-content model status, active/queued counts and observed idle seconds. No prompts, chat messages, database contents, or filenames.
- Existing RAM/Swap guards, personal memories, chat history, gallery outputs, and configured models are untouched.

The optional launchd template at `launchd/optional/de.nobby.mlx-chat-idle.plist.template` is **not** in the main installer template directory and is not activated by standard `install-launchd.sh`. It contains `--apply`; do **not** install until real local acceptance has passed.

## Essential unresolved boundary

Direct clients of port **8000** can bypass the MLX-Nobby shared runtime lease. Metrics cannot guarantee atomic exclusion against an uncoordinated request that starts **after the last poll but before POST /unload**. The script is therefore draft-only until either the installed MLX-VLM's unload-vs-request locking is independently confirmed or all client traffic is known to flow through coordinated Agent routes. The synthetic tests do **not** establish this safety property.

The installed build may also retain a Metal allocator cache after unload. Actual macOS memory reclaim must be measured. The 27B/DFlash2 cold-start and first-token latency must be checked, especially on streamed chats, after an authorized test unload.

## Acceptance and rollback

1. Verify a current private backup, valid configuration, and the complete test suite. Do not disrupt existing chat or media jobs.
2. Read-only after code-only deployment: `cd ~/mlx-web && runtime-venv/bin/python scripts/chat-idle-manager.py --check`. Confirm the actual shapes and numeric values of `/metrics` and `/api/runtime/reliability`. Never infer activity from a port alone.
3. In a separately approved idle window, test one deliberate `POST /unload`, check port 8000 still responds, the model drops from `/health`, physical memory is reclaimed, and an ordinary chat request cold-loads the same 27B model and finishes with correct streaming behavior.
4. Test an in-flight >600s stream, Agent tool gaps and an incoming request near the expiry boundary; no model may unload prematurely. Confirm direct 8000 traffic safety before opt-in.
5. Only then install the **optional** LaunchAgent. Rollback is the targeted `launchctl bootout gui/$(id -u)/de.nobby.mlx-chat-idle`, not `restart-all`. The program does not write private memory or change the 4B router policy.
6. Validate a real Juggernaut XL image and LTX video and compare per-job Swap delta. Do not loosen RAM guard thresholds.

This is an **opt-in draft**. Neither tests nor this PR itself run any real model, issue a live POST /unload, or modify the user's deployed system.
