> Historical experiment record. For current defaults, acceptance status and
> reproduction instructions, use the [integration report](HYBRID_APC_DFLASH_FINAL_REPORT.md)
> and [benchmark runbook](HYBRID_APC_DFLASH_BENCHMARK.md). Earlier PASS labels
> cover their stated checks only; they do not certify release readiness.

# Fixed-history control for hybrid checkpoint experiments

## Finding from the user's Apple Silicon Mac

All 19 targeted tests passed. With the normal, **self-generated** three-turn
conversation, the three causal variants yielded:

| Variant | Extra prefill split | Early snapshot store/turn | Turn 1 chars | Turn 3 APC matched |
|---|---|---|---:|---:|
| OFF | No | 0 | 1805 | 0 |
| SPLIT_ONLY | Yes | 0 | 1370 | 725 |
| ON | Yes | 1 | 1370 | 725 |

The turn-one text was **exactly equal** between SPLIT_ONLY and ON, but
low similarity (0.127) between either and OFF. SPLIT_ONLY achieved the
same third-turn cache reuse without the extra snapshot, so extra cache
storage **is not needed for that specific result**.

However, the benchmark fed each run's newly generated assistant replies
into its own later prompts. Different first-turn answers created different
turn-two and turn-three prompts. This prevents a strict causal comparison
of cache matches for the *same* input conversation.

## Fixed-history replay

New `--replay-answers FILE` mode in the basic three-turn benchmark
reuses a validated captured baseline assistant answer after each turn,
**without replacing the actual generated output being measured**.

The causal benchmark optionally uses the first OFF run's captured answers
as the fixed history for SPLIT_ONLY and ON. Therefore all three variants
receive the same user and assistant messages in each prompt.

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/experiment/hybrid-fixed-history-replay

./test-venv/bin/python -m pytest -q \
  tests/test_benchmark_chat_cache.py \
  tests/test_hybrid_prefill_causal.py \
  tests/test_cache_response_parity.py \
  tests/test_hybrid_early_checkpoint.py \
  tests/test_hybrid_apc_dflash_runtime.py

./test-venv/bin/python -m py_compile \
  scripts/benchmark-chat-cache.py \
  scripts/benchmark-chat-cache-causal.py

./runtime-venv/bin/python scripts/hybrid_apc_dflash_runtime.py --check-only

python3 scripts/benchmark-chat-cache-causal.py \
  --confirm-restarts --capture-answers --fixed-history
```

**Caution:** four model server restarts, interruption of other inference,
and opt-in raw model output capture. Do not run with competing clients.

The script restores both launchctl flags on normal exit. Report path:
`/tmp/chat-cache-causal-report.json`. Private answer captures:
`/tmp/chat-cache-causal-report-answers/*.json` (0700 directory, 0600 files).

## What the controlled results can tell us

- If SPLIT_ONLY and ON produce the same first answer and same cache hit
  counts with *fixed* prompts, early storage may be unnecessary in this
  specific workload; still assess cache memory, eviction and other prompts.
- If SPLIT_ONLY misses on turn 3 while ON hits with fixed prompts, the
  extra early snapshot does have a distinct caching effect with that
  context and should be evaluated for cost/benefit.
- The first-turn responses should still be compared manually. Any
  difference occurs before cache reuse and may be due to prefill chunking,
  model numerical behavior or another reproducibility factor.
- No text-similarity or cache-hit result is automatic semantic approval.
  Check accuracy, hallucinations, RAG boundaries and relevance in
  human review before enabling on `main`.

This is an experimental branch stacked on the response-parity and causal
PRs, **not** an approved release. Early checkpoint flags remain OFF by
default; neither the model nor the installed mlx-vlm files are altered.
