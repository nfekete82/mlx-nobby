# Cache-friendly clock context (conservative first pass)

## Root cause

Real browser chat showed only 187 common MLX token IDs between turns.
The upstream system prompt was unchanged; the injected profile context was not.
In `agent/profile.py`, `system_clock.context()` writes a new second-precision
timestamp at the **start** of every profile string. Subsequent profile facts,
response style and chat history were therefore beyond the exact-cache match.

## Change

For ordinary, text-only, confidently timeless browser requests, web backend
calls `GET /api/profile/context?include_clock=0`. Profile facts and styling
remain unchanged, but the changing clock section is omitted. Temporal words,
dates, time-related system instructions, ambiguous requests and multimodal
content retain `include_clock=1`, preserving the authoritative per-turn time.

The profile endpoint and internal callers default to `include_clock=True`
for backwards compatibility. This intentionally trades off the clock's
availability in implicit time questions against prefix stability. The heuristic
is conservative but not perfect. It should **not** be described as a complete
solution for temporal or RAG-enriched chat turns.

## Local verification

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/fix/hybrid-stable-clock-context
./test-venv/bin/python -m pytest -q tests/test_clock_context_routing.py tests/test_profile.py tests/test_system_clock.py tests/test_prompt_stage_diagnostics.py
./scripts/mlx agent restart
MLX_PROMPT_STAGE_DIAG=1 docker compose up -d --build --force-recreate --no-deps mlx-web
```

The Agent restart is required because the profile endpoint runs in the
LaunchAgent process, not inside the Docker web service.

In a new browser chat, send the 3 Apple-Silicon questions. Read:

```bash
docker logs mlx-web 2>&1 | grep PROMPT_STAGE_DIAG | tail -20
./scripts/mlx chat-profile status
```

Expected for these questions: `with_profile system_unchanged=True`,
unless profile settings are edited between turns. APC exact hits may still be
blocked by RAG or changes further down the prompt pipeline; check runtime stats.

Test a temporal question in a **new** chat (e.g. "Welches Datum haben wir heute?")
and ensure current host date is returned.

## Rollback

Disable optimization without changing Git branches:

```bash
NOBBY_CLOCK_CONTEXT_ALWAYS=1 docker compose up -d --force-recreate --no-deps mlx-web
```

After verifying, disable logs with:

```bash
docker compose up -d --force-recreate --no-deps mlx-web
```

If `NOBBY_CLOCK_CONTEXT_ALWAYS=1` was stored in `.env`, remove it to
re-enable adaptive routing. This is an **opt-out** setting; its default is 0.

No cache key, checkpoint, model weights, or chat role boundaries change.
