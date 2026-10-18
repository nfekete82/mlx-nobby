> Historical experiment record. For current defaults, acceptance status and
> reproduction instructions, use the [integration report](HYBRID_APC_DFLASH_FINAL_REPORT.md)
> and [benchmark runbook](HYBRID_APC_DFLASH_BENCHMARK.md). Earlier PASS labels
> cover their stated checks only; they do not certify release readiness.

# Hybrid cache Release Candidate 1

## Scope

This candidate integrates the stacked work originating in the prompt-stage
diagnosis through the early-checkpoint soak branch. It is based on
`test/hybrid-checkpoint-soak-quality` and targets `main` as a **draft**;
it must not be interpreted as already merged or released.

## Observed on M5 Max Mac

- 10/10 relevant CPU checks passed in the latest targeted soak suite.
- Alternating five OFF / five ON runs, restarting the model server every run.
- With early checkpoint ON, turn 3 reused 725 tokens in 5/5 runs.
- With early checkpoint OFF, turn 3 got 0 exact hits in 5/5 runs.
- Median time to first content on turn 3: 2195 ms OFF, 1241 ms ON.
- Median total turn-3 time: 18682 ms OFF, 18572 ms ON.
- A/B release gates PASS; measured median swap delta 0.0 GB.
- The ON and OFF answer lengths differ; equal semantic quality has **not**
  been demonstrated.
- Short A/B runs and global cumulative counters do not establish broad
  production speedups, especially under concurrent requests.

## Deployment policy

- `NOBBY_HYBRID_EARLY_CHECKPOINT` is OFF by default.
- `NOBBY_HYBRID_CACHE_DIAG` is OFF by default.
- `NOBBY_RAG_LATE_CONTEXT` is OFF by default.
- `MLX_PROMPT_STAGE_DIAG` is OFF by default.
- Existing clock routing defaults to stable profile context for timeless
  prompts; `NOBBY_CLOCK_CONTEXT_ALWAYS=1` restores unconditional clock.
- The Hybrid adapter remains an explicit experimental runtime profile.

No changes to installed `mlx_vlm` source files. No automatic activation.
Keep version/source validation for MLX-VLM 0.6.17.

## Release blockers to resolve before enabling by default

1. Run complete Python/JS/browser regression suites on the target Mac.
2. Review representative OFF vs ON responses for factual completeness,
   instruction handling and local RAG grounding, not just answer length.
3. Run a long-lived in-process cache session (without restarts) to monitor
   RSS, swap, evictions, and failures over many turns.
4. Verify frontend browser prompts, RAG injection, and fallback behavior.
5. Review restore/rollback commands and inspect change impact in Docker,
   Agent profile, and runtime launcher.
6. Obtain human review of any changes affecting context trust boundaries.

## Suggested acceptance commands

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/release/hybrid-cache-rc1
./test-venv/bin/python -m pytest -q \
  tests/test_clock_context_routing.py \
  tests/test_rag_prefix_placement.py \
  tests/test_prompt_stage_diagnostics.py \
  tests/test_hybrid_cache_diagnostics.py \
  tests/test_hybrid_early_checkpoint.py \
  tests/test_hybrid_apc_dflash_runtime.py \
  tests/test_benchmark_chat_cache.py \
  tests/test_chat_cache_ab.py \
  tests/test_chat_cache_turn_diagnostics.py \
  tests/test_checkpoint_release_gates.py \
  tests/test_checkpoint_soak_quality.py
./runtime-venv/bin/python scripts/hybrid_apc_dflash_runtime.py --check-only
./scripts/mlx chat-profile status
```

No model restarts are needed to run these CPU and compatibility checks.
