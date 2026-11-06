# Automatic dedicated 4B memory model

The new de.nobby.mlx-memory-supervisor LaunchAgent owns **only** its
own local mlx_vlm child serving the exact local
~/Models/router/Qwen3.5-4B-MLX-4bit checkpoint at 127.0.0.1:8011.
It never stops or switches the foreground chat model, Docker or native media.

## Operational behavior

- When dedicated extraction is enabled, 4B is kept warm when the system
  reports at least 25% free memory and loading 5 GB does not exceed the
  existing 90% hard admission limit. A chat does not need to stay open.
- Text-to-image generations through the Agent-owned media queue now always
  request a bounded, exclusive release of the supervisor-owned 4B **before**
  native image dispatch, even if an idle memory snapshot looks healthy.
  This covers automatic image model selection as well as explicit Juggernaut XL.
  Background extraction keeps its inference lock: the queued image waits and
  retries rather than interrupting the in-flight extraction or losing its job.
- Image edits, upscaling and video keep the existing headroom/pressure-based 4B
  release policy. Non-supervisor-owned (external/manual) port 8011 is never
  killed. The native media hard limits, swap-growth watchdog and safety gates
  are unchanged.
- Running extraction is protected by a cross-process lock. New extraction
  defers without consuming the durable SQLite job's retry allowance.
- A user cancellation arriving while the 4B is draining is checked again
  before native dispatch; the cancelled job cannot begin rendering.
- The supervisor can terminate ONLY its own 4B child. Running media jobs
  keep priority, then 4B resumes when memory becomes available.
- If port 8011 is already owned by a manually started process, the
  supervisor reports external and never kills that process.
- Chat, source histories, memory data, the 46 historical conflicts, model
  selection, and all other MLX runtimes are untouched.
- Preemption is integrated with the Agent-owned queue; direct clients of
  native media services still rely on their existing RAM admission guards.

## Install and inspect

Stop the manually launched 4B server with Ctrl-C in its own terminal
before the first installation. Then, from the updated production checkout:

    bash ~/mlx-web/scripts/install-memory-supervisor.sh

Only the new LaunchAgent is installed, not the entire MLX service suite.
The regular install-launchd helper also picks up its template.

The queue worker is in the native Agent process (port 8010); changes to the
queue and supervisor policy require updating/restarting **those two** services
during an approved local rollout, *not* the Docker web UI. Use an idle queue
and a verified private backup before the restart. Do not restart a GPU media
worker or interrupt an active extraction. This PR does not run a GPU job.

    curl -fsS http://127.0.0.1:8010/api/smart-memory/supervisor
    cat ~/.config/mlx-web/memory-model-control/state.json
    launchctl print "gui/$(id -u)/de.nobby.mlx-memory-supervisor"

Supervisor states: starting, running, external, suspended_media,
suspended_pressure, waiting_for_memory and disabled. Waiting means
the worker keeps its SQLite jobs until memory is available.

## Rollback (without memory deletion)

Return to the original extraction backend:

    curl -fsS -X POST http://127.0.0.1:8010/api/smart-memory/model -H 'Content-Type: application/json' -d '{"mode":"chat"}'

Unload ONLY this supervisor:

    launchctl bootout "gui/$(id -u)/de.nobby.mlx-memory-supervisor"

No DB migration, private history re-analysis or automatic conflict
resolution is included. Under sustained RAM pressure 4B may be paused
indefinitely until the machine has adequate memory.

## 2026-11-06 — release tests and limits

Offline regression coverage: `tests/test_memory_model_supervisor.py` and
`tests/test_media_queue.py`. They simulate healthy RAM, exclusive priority,
protected 4B extraction, safe deferral and retry, external port ownership,
cancellation during memory handoff and later resumption. No memory databases,
checkpoints or model files are touched in tests.

Real-world acceptance remains separate: with Qwen 27B, supervised Memory 4B and
one normal Juggernaut XL **Ultra** image, check that 4B suspends before dispatch,
chat temporarily stops inside the image runtime, and both return after the image
worker has unloaded. Record RAM pressure and swap growth. If a RAM guard trips,
retain the safe abort and gather diagnostics; **do not** raise limits or
automatically retry. Ultra+ remains hidden from the regular UI.
