> Historical experiment record. For current defaults, acceptance status and
> reproduction instructions, use the [integration report](HYBRID_APC_DFLASH_FINAL_REPORT.md)
> and [benchmark runbook](HYBRID_APC_DFLASH_BENCHMARK.md). Earlier PASS labels
> cover their stated checks only; they do not certify release readiness.

# Extended hybrid checkpoint soak and quality gate

This branch retains early checkpoints OFF by default. An optional longer A/B
run samples memory before and after each conversation, and explicitly
marks semantic output quality as *pending manual review*.

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/test/hybrid-checkpoint-soak-quality
./test-venv/bin/python -m pytest -q tests/test_checkpoint_soak_quality.py tests/test_chat_cache_ab.py tests/test_checkpoint_release_gates.py tests/test_hybrid_early_checkpoint.py
./test-venv/bin/python -m py_compile scripts/benchmark-chat-cache-ab.py

./scripts/mlx benchmark chat-cache-ab --confirm-restarts --pairs 5 --release-gates --quality-review
```

**Disruptive:** ten benchmark conversations, eleven model restarts including
restoration. Only run when all other model work is idle. A/B timings and
cache counters are not exclusive to the test if other callers are active.

The report includes `memory_before_run`, `memory_after_run`,
`memory_delta_swap_gb`, and `quality_review: PENDING`. The previous
release gate remains a preliminary, automatic technical gate; **PASS is not a
substitute for correctness evaluation**. Compare representative outputs
manually. No response texts are stored in JSON by default.

Verify final status and restored environment after the command:
```bash
launchctl getenv NOBBY_HYBRID_EARLY_CHECKPOINT
./scripts/mlx chat-profile status
```
