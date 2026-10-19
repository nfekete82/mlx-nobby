> Historical experiment record. For current defaults, acceptance status and
> reproduction instructions, use the [integration report](HYBRID_APC_DFLASH_FINAL_REPORT.md)
> and [benchmark runbook](HYBRID_APC_DFLASH_BENCHMARK.md). Earlier PASS labels
> cover their stated checks only; they do not certify release readiness.

# Alternating early-checkpoint A/B benchmark

The latest live run with early checkpoints got a third-turn APC hit
(1057 tokens). This alone does not establish causality: the answer tokens
differed from the earlier control, and 1057 matched the prior *normal*
checkpoint rather than the earlier 897-token checkpoint.

This tool explicitly compares fresh model-server sessions with the feature
OFF and ON, alternating the variants to reduce order bias.

## Run only when you're ready for multiple model server restarts

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/experiment/hybrid-checkpoint-ab-benchmark
./test-venv/bin/python -m pytest -q \
  tests/test_chat_cache_ab.py \
  tests/test_benchmark_chat_cache.py \
  tests/test_hybrid_early_checkpoint.py \
  tests/test_hybrid_apc_dflash_runtime.py
./test-venv/bin/python -m py_compile scripts/benchmark-chat-cache-ab.py
./runtime-venv/bin/python scripts/hybrid_apc_dflash_runtime.py --check-only

./scripts/mlx benchmark chat-cache-ab --confirm-restarts --pairs 2
```

The command performs four runs (OFF, ON, OFF, ON), restarts MLX before each
run, records all per-turn cache counts and latencies, and writes
`/tmp/chat-cache-ab-report.json`. It also captures post-run memory
pressure/swap from Agent Observatory if available.

**Warning**: this script interrupts all active MLX generation, including
other users. Run only when idle. It does not alter the chat profile or Docker.
It attempts to restore the previous early-checkpoint environment setting
and restart MLX in `finally` even if a benchmark fails. Check the service
status and environment afterward. On SIGKILL or power loss, cleanup cannot
run. CLI requires `--confirm-restarts` to avoid accidental impact.

The per-turn cache hit counts are shared-server deltas; avoid concurrent
chats. Responses will not be identical even with temperature 0 on all
implementations. Four runs are exploratory and too few for definitive
performance conclusions. Use paired runs, inspect similar lengths and swap,
and repeat if differences are noisy. Current user-system-prompt parity with
the browser is not guaranteed.

## Clean up and check

```bash
launchctl getenv NOBBY_HYBRID_EARLY_CHECKPOINT
./scripts/mlx chat-profile status
```

No model cache logic was modified in this PR; this is a measurement tool.
