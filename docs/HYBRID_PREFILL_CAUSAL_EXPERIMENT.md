> Historical experiment record. For current defaults, acceptance status and
> reproduction instructions, use the [integration report](HYBRID_APC_DFLASH_FINAL_REPORT.md)
> and [benchmark runbook](HYBRID_APC_DFLASH_BENCHMARK.md). Earlier PASS labels
> cover their stated checks only; they do not certify release readiness.

# Hybrid prefill causal experiment (early-checkpoint response divergence)

## Why

The five-pair OFF/ON soak showed 0/5 vs 5/5 turn-three exact cache
hits. However, with `temperature=0`, ON and OFF gave different
**first-turn** answers (1805 vs 1370 chars) even though both had
zero cache hits. Repeated answer lengths suggest systematic changes,
but lengths alone cannot establish answer quality or mathematical
equivalence.

At present, enabling the early checkpoint changes the **prefill chunk
boundaries** to land on a 160-token-early snapshot position. It also
stores a second exact-cache snapshot. The existing test did not separate
these effects.

## Controlled modes

| Mode | Early prefill split | Save early cache snapshot |
|---|---|---|
| OFF | No | No |
| SPLIT_ONLY | Yes | No |
| ON | Yes | Yes |

The runtime-only flag `NOBBY_HYBRID_EARLY_CHECKPOINT_STORE=0` is
diagnostic: it disables only the early snapshot store; the early split
still occurs. By default it is `1`, preserving existing behavior.
Normal hybrid cache checkpoints are unchanged. This flag is honored
only when `NOBBY_HYBRID_EARLY_CHECKPOINT=1`.

## Run on Mac (when model is idle)

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/experiment/hybrid-prefill-split-control

./test-venv/bin/python -m pytest -q \
  tests/test_hybrid_prefill_causal.py \
  tests/test_cache_response_parity.py \
  tests/test_hybrid_early_checkpoint.py \
  tests/test_hybrid_apc_dflash_runtime.py \
  tests/test_benchmark_chat_cache.py
./test-venv/bin/python -m py_compile \
  scripts/benchmark-chat-cache-causal.py \
  scripts/hybrid_apc_dflash_runtime.py
./runtime-venv/bin/python scripts/hybrid_apc_dflash_runtime.py --check-only

python3 scripts/benchmark-chat-cache-causal.py \
  --confirm-restarts --capture-answers
```

The command restarts the model server **four times**, including the
final restoration, and temporarily interrupts all other inference.
Do not run while any other model job is active.

The report at `/tmp/chat-cache-causal-report.json` contains mode-level
cache deltas, first-turn lengths, exact equality and text similarity,
but not raw answer strings.

With explicit capture opt-in, raw response files appear under
`/tmp/chat-cache-causal-report-answers/` (0700 folder, 0600 files).
These files can include private RAG content; review before sharing and
do not add them to GitHub.

Both diagnostic environment variables are restored to their exact
original values (including unset) in `finally`. Note hard termination
or a power failure prevents restoration, so verify state afterward:

```bash
launchctl getenv NOBBY_HYBRID_EARLY_CHECKPOINT
launchctl getenv NOBBY_HYBRID_EARLY_CHECKPOINT_STORE
./scripts/mlx chat-profile status
```

## Interpretations

- OFF differs from SPLIT_ONLY, while SPLIT_ONLY equals ON on turn 1:
  supports the hypothesis that changing prefill chunks, not storing the
  cache snapshot, changes first-turn generation.
- OFF equals SPLIT_ONLY, while SPLIT_ONLY differs from ON on turn 1:
  focus on unintended side effects of snapshot storage.
- All three differ or all match: investigate backend nondeterminism,
  model cache state, prompt parity and run-to-run variability.
- Any third-turn zero-hit SPLIT_ONLY run is expected; normal full
  checkpoints may still produce hits independently.

**No automatic semantic PASS.** First-turn and later responses require
manual inspection. If extra split boundaries alter generation,
do not enable this feature by default until a numerically validated
strategy or an acceptable variation policy is documented.
