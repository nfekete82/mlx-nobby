> Historical experiment record. For current defaults, acceptance status and
> reproduction instructions, use the [integration report](HYBRID_APC_DFLASH_FINAL_REPORT.md)
> and [benchmark runbook](HYBRID_APC_DFLASH_BENCHMARK.md). Earlier PASS labels
> cover their stated checks only; they do not certify release readiness.

# Hybrid APC: early snapshot at native prefill boundaries

## Motivation

The M5 Max fixed-history hardware experiment confirmed that **two exact APC
slots** retain an early 826-token cache entry. The third request could then
reuse 826 tokens (vs 324 for the ordinary two-slot baseline, and zero for
the one-slot baseline). This demonstrates a real cache-reuse improvement
for identical text prompts, not merely changed assistant transcripts.

However, the forced early boundary changes the first generated answer,
even on turn 1 where there are zero cache hits. The observed
baseline-vs-forced first-turn similarity was about 0.127. Response
quality and numerical parity remain blocking issues.

## Experiment: natural chunk boundaries

New opt-in `NOBBY_HYBRID_EARLY_CHECKPOINT_ALIGN_NATIVE=1` rounds the
secondary checkpoint **down** from its usual `checkpoint-160` target
to the most recent boundary already reached by the ordinary prefill
chunk loop. Since chunks start at the matched-token offset, the
alignment uses `matched + n * prefill_step_size`; this avoids creating
an extra `lm(...n_to_process=...)` inference call just to save a
cache checkpoint. If no valid earlier boundary exists, skip early
saving for that turn. The existing early-checkpoint and two-slot
feature flags are still required.

The CPU policy does not guarantee numerical output equality; copying
an MLX cache snapshot may still introduce memory/synchronization
effects. Only the Apple Silicon hardware test can establish observed
parity. This does not alter the installed mlx-vlm package.

## Four-arm fixed-history experiment

| Mode | Exact cache slots | Early snapshot | Forced extra chunk split |
|---|---:|---|---|
| baseline1 | 1 | No | No |
| baseline2 | 2 | No | No |
| early2 | 2 | Forced at checkpoint-160 | Yes |
| native2 | 2 | Natural boundary <= checkpoint-160 | No |

All cases replay the same baseline assistant history from the first run,
so each turn has the same model prompt. They run at temperature zero.
Raw responses are only captured with explicit opt-in and stay local
(`/tmp/chat-cache-causal-report-answers/`, mode 0700 dir and 0600 files).

### Test on Mac

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/experiment/hybrid-native-prefill-boundary

./test-venv/bin/python -m pytest -q \
  tests/test_hybrid_native_prefill_boundary.py \
  tests/test_hybrid_exact_cache_slots.py \
  tests/test_hybrid_fixed_history_prefix_gap.py \
  tests/test_benchmark_chat_cache.py \
  tests/test_hybrid_prefill_causal.py \
  tests/test_cache_response_parity.py \
  tests/test_hybrid_cache_diagnostics.py \
  tests/test_hybrid_early_checkpoint.py \
  tests/test_hybrid_apc_dflash_runtime.py

./test-venv/bin/python -m py_compile \
  scripts/hybrid_checkpoint_policy.py \
  scripts/hybrid_apc_dflash_runtime.py \
  scripts/benchmark-chat-cache-causal.py

./runtime-venv/bin/python scripts/hybrid_apc_dflash_runtime.py --check-only

python3 scripts/benchmark-chat-cache-causal.py \
  --confirm-restarts --capture-answers --fixed-history \
  --diagnose --compare-native
```

This uses four three-turn conversations and **five** model-server restarts
including the final configuration restoration. Do not run other GPU/model
jobs concurrently. The script restores all tracked launchctl feature
flags (including unset values); hard interruption can prevent cleanup.

### How to evaluate

- Does `native2` equal `baseline1` / `baseline2` on turn 1?
  This is the main parity test; a matching character count alone is
  insufficient, so the benchmark reports **exact text equality**.
- Does `native2` obtain more than the baseline 324 reused tokens on
  turn 3 under identical history? This demonstrates a meaningful
  retained early cache snapshot without a forced chunk split.
- Does swapping or runtime memory pressure increase due to two large
  entries? Two entries is *not* a strict byte-size bound.
- If native2 misses while early2 hits, the native boundary may be too
  early, cloned cache state may be unsuitable or capacity/eviction may
  still matter. Inspect numeric HYBRID_APC_LRU diagnostic entries.
- A text-equality result on one prompt is not semantic certification.
  Run multiple prompts, evaluate later-turn answers and security
  grounding before shipping this as a default feature.

## Release gate

Feature flags remain off by default. This branch is experimental and
should not yet be merged to main as a generally faster or equivalent
generation implementation.
