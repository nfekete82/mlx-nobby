> Historical experiment record. For current defaults, acceptance status and
> reproduction instructions, use the [integration report](HYBRID_APC_DFLASH_FINAL_REPORT.md)
> and [benchmark runbook](HYBRID_APC_DFLASH_BENCHMARK.md). Earlier PASS labels
> cover their stated checks only; they do not certify release readiness.

# Prompt stage stability: browser to Agent

The hybrid probe recorded a stable semantic hash but only **187 matching
model tokens** across consecutive browser chat turns. Browser diagnostics
showed unchanged previous messages and a stable base system prompt.

In `backend/app.py`, profile context, RAG results, public web research and
inflation context may be inserted into the leading system message. We have
**not established which stage changes**; moving trusted system context into
user messages would weaken instruction priority, so this PR measures each
stage first rather than changing its semantics.

The opt-in check logs only lengths and common character prefix lengths
of the leading system message across consecutive requests. It stores one
bounded comparison copy of that content in the process RAM only. No text,
hashes, query, trace ID or answers are sent to logs. Comparisons are global
within one web worker: do not mix sessions while testing.

## On the Mac

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/diag/chat-prompt-stage-stability
./test-venv/bin/python -m pytest -q tests/test_prompt_stage_diagnostics.py
MLX_PROMPT_STAGE_DIAG=1 docker compose up -d --build --force-recreate --no-deps mlx-web
```

Open a **new browser chat** and send three related, text-only questions.
Use no other conversations concurrently. Read:

```bash
docker logs mlx-web 2>&1 | grep PROMPT_STAGE_DIAG | tail -25
```

Inspect where `system_unchanged` first becomes false or
`common_prefix_chars` drops. This locates the changing stage, not
necessarily the exact model-token offset.

Disable and rebuild without the debug environment:

```bash
docker compose up -d --force-recreate --no-deps mlx-web
```

The Compose environment defaults to zero. To override a value explicitly
stored in a project `.env`, unset or remove it there too.

The hybrid runtime and its exact-cache matching are untouched.

## Verified 2026-10-18 browser diagnosis

Three subsequent requests yielded stable base system text (649 characters),
but the same-length profile system text (2152 characters) diverged after
710 characters. Turn two added 816 RAG characters; turn three did not.

Source inspection identifies the primary mutable prefix:
`agent/profile.py:context()` begins with `system_clock.context()`.
The latter injects `datetime.now().astimezone()` with **second precision**
in `agent/system_clock.py`, so the leading system message changes every
turn even if the user profile and prior messages are unchanged.

This is a confirmed prompt-drift cause, not a confirmed cache-engine bug.
A safe fix must preserve authoritative per-turn clock information and system
instruction precedence while moving or isolating mutable time context.
Do **not** merely freeze the clock or move trusted instructions into
untrusted source snippets to force APC hits. The MLX chat template's support
for late system messages and runtime partial-prefix reuse must be assessed
before choosing a solution.
