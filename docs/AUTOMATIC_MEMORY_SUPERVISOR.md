# Automatic dedicated 4B memory model

The new de.nobby.mlx-memory-supervisor LaunchAgent owns **only** its
own local mlx_vlm child serving the exact local
~/Models/router/Qwen3.5-4B-MLX-4bit checkpoint at 127.0.0.1:8011.
It never stops or switches the foreground chat model, Docker or native media.

## Operational behavior

- When dedicated extraction is enabled, 4B is kept warm when the system
  reports at least 25% free memory and loading 5 GB does not exceed the
  existing 90% hard admission limit. A chat does not need to stay open.
- Image/video requests through the Agent-owned media queue ask for
  4B RAM relief BEFORE native dispatch if the coordinator's existing
  load reserve indicates insufficient headroom.
- Running extraction is protected by a cross-process lock. New extraction
  defers without consuming the durable SQLite job's retry allowance.
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
