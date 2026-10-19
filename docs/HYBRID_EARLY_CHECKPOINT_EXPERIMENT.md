> Historical experiment record. For current defaults, acceptance status and
> reproduction instructions, use the [integration report](HYBRID_APC_DFLASH_FINAL_REPORT.md)
> and [benchmark runbook](HYBRID_APC_DFLASH_BENCHMARK.md). Earlier PASS labels
> cover their stated checks only; they do not certify release readiness.

# Early exact checkpoint experiment (MLX-VLM 0.6.17)

## Evidence

On the Mac, benchmark turn 3 had 1705 tokens; the previous checkpoint had
1073 tokens, but only 965 tokens remained identical. Semantic hash matched.
The existing APC lookup missed. Turn 2 successfully reused 324 tokens.

## Experiment

Default **OFF**. If `NOBBY_HYBRID_EARLY_CHECKPOINT=1` reaches the MLX
LaunchAgent, the hybrid adapter additionally saves a **genuine live prefill
cache snapshot** 160 tokens before the final checkpoint (not a slice of an
already-mutated long cache).

The ordinary final checkpoint, token guards, exact hashes, speculative
decoding and model weights are unchanged. The extra snapshot requires
processing an exact earlier boundary to maintain correctness. This adds a
store and memory/copy cost, and the cache manager may evict or replace it.
**This experiment cannot guarantee that the manager will select it.**

## Hardware checks

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/experiment/hybrid-early-checkpoint
./test-venv/bin/python -m pytest -q \
  tests/test_hybrid_early_checkpoint.py \
  tests/test_hybrid_apc_dflash_runtime.py \
  tests/test_hybrid_cache_diagnostics.py \
  tests/test_benchmark_chat_cache.py
./runtime-venv/bin/python scripts/hybrid_apc_dflash_runtime.py --check-only

launchctl setenv NOBBY_HYBRID_EARLY_CHECKPOINT 1
launchctl setenv NOBBY_HYBRID_CACHE_DIAG 1
./scripts/mlx restart
./scripts/mlx benchmark chat-cache --diagnose
./scripts/mlx chat-profile status
grep 'Hybrid early checkpoint stored' ~/.config/mlx-web/server-error.log | tail -6

# Stop experiment and restore the prior runtime configuration:
launchctl unsetenv NOBBY_HYBRID_EARLY_CHECKPOINT
launchctl unsetenv NOBBY_HYBRID_CACHE_DIAG
./scripts/mlx restart
```

Interpretation: compare turn 3 exact-hit and matched-token deltas to the
baseline 0/0. A failed early checkpoint store is logged and the ordinary
checkpoint is still attempted. If the model server fails to initialize,
disable the feature as above and report logs. Run with no other model chat
traffic. Keep the PR draft until real Apple Silicon validation confirms
output quality, correct snapshot semantics, CPU/GPU memory behavior,
and no change in cache validity.

The diagnostic classifier only tracks the **last** successful final stored
checkpoint; it may classify the third-turn lookup as matching a different
prefix even if the manager finds the earlier one. Treat manager hit counts
as authoritative for actual reuse.
