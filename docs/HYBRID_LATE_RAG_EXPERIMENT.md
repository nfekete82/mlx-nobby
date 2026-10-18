> Historical experiment record. For current defaults, acceptance status and
> reproduction instructions, use the [integration report](HYBRID_APC_DFLASH_FINAL_REPORT.md)
> and [benchmark runbook](HYBRID_APC_DFLASH_BENCHMARK.md). Earlier PASS labels
> cover their stated checks only; they do not certify release readiness.

# Experimental late RAG placement for APC

Observed: clock routing fixed profile stability, but browser turns with automatic
knowledge search still added 816 chars to the leading system prompt on turn 2,
breaking the prior checkpoint. In this **opt-in experiment**, a stable trusted
system policy describes how to handle retrieved material and forbids obeying
instructions from it. Variable retrieved snippets are appended only to the
current user's text as delimited *reference data*; earlier messages and the
leading system prompt stay unchanged.

Default: `NOBBY_RAG_LATE_CONTEXT=0`. This is not yet verified on Apple Silicon,
and retrieval semantics differ from the historical system-message placement.
A model can still be susceptible to prompt injection: confirm it doesn't obey
hostile instructions in retrieved content. Multimodal/non-text turns revert
to the prior system placement. Cache hits are **not guaranteed**, and other
dynamic web contexts can still change the prefix.

## Mac validation

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/fix/hybrid-rag-late-context
./test-venv/bin/python -m pytest -q tests/test_rag_prefix_placement.py tests/test_clock_context_routing.py tests/test_prompt_stage_diagnostics.py
NOBBY_RAG_LATE_CONTEXT=1 MLX_PROMPT_STAGE_DIAG=1 docker compose up -d --build --force-recreate --no-deps mlx-web
```

Test in a **new chat** with the three Apple Silicon follow-ups. Check:

```bash
docker logs mlx-web 2>&1 | grep -E 'PROMPT_CLOCK_DECISION|PROMPT_STAGE_DIAG' | tail -25
./scripts/mlx chat-profile status
```

Expected: `with_profile` stable and `with_rag` stable on all three turns.
This is only a text-level prerequisite for APC: the runtime still needs to
match its tokenized checkpoint; use exact hit metrics to verify real gains.
Also ask a relevant local-knowledge question, confirm sources are used, and
try a prompt-injection-bearing knowledge document if safe in a test-only KB.

## Disable

```bash
# Default is disabled when no .env overrides are present.
docker compose up -d --force-recreate --no-deps mlx-web
```

If your environment persists the opt-in variable in a .env file, clear it
there as well. Diagnostic logging can be disabled independently.
