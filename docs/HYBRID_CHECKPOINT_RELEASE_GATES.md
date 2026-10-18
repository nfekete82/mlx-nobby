# Hybrid checkpoint release gates

The two-pair A/B run showed repeatable turn-three cache hits only with the
early checkpoint ON, but does **not** yet justify enabling it by default.

This branch keeps the feature disabled by default and adds optional release
gate reporting to the existing A/B benchmark.

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/test/hybrid-checkpoint-release-gates
./test-venv/bin/python -m pytest -q \
 tests/test_checkpoint_release_gates.py \
 tests/test_chat_cache_ab.py \
 tests/test_hybrid_early_checkpoint.py \
 tests/test_hybrid_apc_dflash_runtime.py
./test-venv/bin/python -m py_compile \
 scripts/checkpoint_release_gates.py \
 scripts/benchmark-chat-cache-ab.py
./scripts/mlx benchmark chat-cache-ab --confirm-restarts --pairs 3 --release-gates
```

**This restarts the model server seven times** (six runs plus restoration).
Only execute when no other jobs/users need the model. It writes a JSON report
with `release_gates` status `PASS` or `REVIEW`; PASS is preliminary and
not a production-approval certificate. Minimum three ON and three OFF runs,
ON third-turn hit rate >= 80%, and median post-run swap increase <= 1 GB.
Missing memory data results in REVIEW rather than an invented result.

A/B model generations can vary despite temperature=0. Compare response
quality manually and monitor memory pressure, not just swap. Confirm the
original launchctl environment and model service status after running.
No production cache behavior changes are included.
