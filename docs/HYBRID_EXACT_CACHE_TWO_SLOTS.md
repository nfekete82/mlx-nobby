# Hybrid exact-cache LRU capacity: one vs two snapshots (MLX-VLM 0.6.17)

## Root cause found in the actual sources

The hybrid profile in `scripts/mlx-server-start` explicitly sets
`APC_EXACT_CACHE_ENTRIES=1`, overriding the MLX-VLM 0.6.17 upstream
default of 2. The upstream `APCManager.store_exact_cache` uses an
ordered-dict LRU, evicts the oldest entry whenever there are more entries
than `_exact_cache_max`, and `lookup_exact_cache` selects the **longest
matching prefix** among retained entries.

In the user's fixed-history run, turn 2 stored a normal 986-token
checkpoint and, with early checkpoint ON, also an 826-token snapshot.
Turn 3 had only 878 tokens in common with turn 2. So 986 does not
match but 826 would. With a **one-entry** capacity, the normal 986-token
store immediately evicts the earlier 826-token store. This precisely
explains the absence of a turn-three hit without requiring a change in
the 160-token guard.

Earlier self-generated-chat hits (725 tokens) resulted from divergent
assistant answers and changing later prompts; not a controlled same-prompt
speed improvement. The first-turn response also differs under alternate
prefill splits, which remains a separate **correctness review blocker**.

## Experiment

The hybrid-only env flag `NOBBY_HYBRID_EXACT_CACHE_ENTRIES=2`
temporarily allows **two** in-memory exact snapshots, without disk
persistence. One remains the default, and invalid overrides fail closed.
The ordinary APC profile is unchanged. This entry limit is **not a
memory-byte limit**, and a hybrid cache snapshot may be large.

A four-arm controlled benchmark runs identical answer-history prompts:

| Mode | Prefill split | Extra early store | Exact slots |
|---|---|---|---|
| baseline1 | No | No | 1 |
| baseline2 | No | No | 2 |
| split2 | Yes | No | 2 |
| early2 | Yes | Yes | 2 |

Expected *hypotheses*, not results: baseline2/split2 might retain the
324-token first-turn checkpoint; early2 might reuse the 826-token early
checkpoint. Actual performance, cache eviction and response quality
must be measured on the Mac.

The adapted runtime logs numeric-only `HYBRID_APC_LRU` capacity and
occupancy when diagnostics are enabled, and no longer falsely logs an
unsuccessful `store_exact_cache` return as a successful snapshot.

## Test on Mac

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/experiment/hybrid-exact-cache-two-slots

./test-venv/bin/python -m pytest -q \
  tests/test_hybrid_exact_cache_slots.py \
  tests/test_hybrid_fixed_history_prefix_gap.py \
  tests/test_benchmark_chat_cache.py \
  tests/test_hybrid_prefill_causal.py \
  tests/test_cache_response_parity.py \
  tests/test_hybrid_cache_diagnostics.py \
  tests/test_hybrid_early_checkpoint.py \
  tests/test_hybrid_apc_dflash_runtime.py

./test-venv/bin/python -m py_compile \
  scripts/benchmark-chat-cache-causal.py \
  scripts/hybrid_apc_dflash_runtime.py

./runtime-venv/bin/python \
  scripts/hybrid_apc_dflash_runtime.py --check-only

python3 scripts/benchmark-chat-cache-causal.py \
  --confirm-restarts --capture-answers \
  --fixed-history --diagnose --compare-slots
```

Four three-turn conversations, **five model restarts including final
restoration**. Only run while MLX inference is otherwise idle; the
script restores all four pre-existing launchctl flag values, including
unset. Hard termination (SIGKILL, power loss) prevents cleanup.

The report `/tmp/chat-cache-causal-report.json` includes numeric
cache statistics, prefix-gap diagnostics and optional before/after
Agent Observatory RAM/Swap telemetry. Raw model answers are written to
owner-only local files under
`/tmp/chat-cache-causal-report-answers/`, not to GitHub.

Verify after testing:

```bash
launchctl getenv NOBBY_HYBRID_EXACT_CACHE_ENTRIES
launchctl getenv NOBBY_HYBRID_EARLY_CHECKPOINT
launchctl getenv NOBBY_HYBRID_CACHE_DIAG
./scripts/mlx chat-profile status
```

## Acceptance caveats

- A cache **hit** proves only that a matching prefix was found. It does
  not prove numerically correct cache continuation or answer parity.
- Additional exact snapshots retain state in RAM. Verify headroom,
  swap and OOM guards before recommending a capacity increase.
- Do not claim production speed improvements or merge the release
  candidate until fixed-history cache hits, output correctness and
  memory behavior are established.
- Keep early checkpoint and two-slot behavior opt-in.
