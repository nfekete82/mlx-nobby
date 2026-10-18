# Hybrid APC: Exact cache miss diagnostics (opt-in)

The Agent route produced exact hits, but normal browser chat produced stores
without reuse. This patch does not alter cache keys or change the number of
entries. It adds an **opt-in** diagnostic log inside the speculative prefill.

The helper retains one bounded tuple of checkpoint token IDs (max 65536) in
process RAM only. **It does not log token IDs, prompt text, semantic hashes,
or output content.** It writes reason codes and lengths via Python logging.
The helper does not persist its snapshot to disk. The exact-cache runtime
already holds token sequences independently.

Reasons: `no_previous_snapshot`, `semantic_hash_changed`,
`token_prefix_changed`, `prefix_shorter_than_checkpoint`,
`lookup_miss_despite_matching_prefix`, `exact_hit`,
`below_minimum`, `too_long_to_track`.

The comparison is with the **last successfully stored checkpoint** in this
process. It cannot prove causes involving server-internal eligibility or a
different snapshot selected by the cache manager.

## Local test

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/diag/hybrid-exact-miss-reasons
./test-venv/bin/python -m pytest -q \
  tests/test_hybrid_cache_diagnostics.py \
  tests/test_hybrid_apc_dflash_runtime.py

# Check compatibility with the installed runtime:
./runtime-venv/bin/python scripts/hybrid_apc_dflash_runtime.py --check-only
```

To run diagnostics, set `NOBBY_HYBRID_CACHE_DIAG=1` in the
**chat server process environment** before restarting that server. Merely
exporting in a separate terminal will not affect an already-running service.
Do not change the user's default chat profile. Clear this environment value
and restart chat to disable diagnostic logging.

Run three text-only requests in the same browser chat, then inspect the
**chat server process logs** for `HYBRID_APC_DIAG`. This is local diagnostic
data; do not enable it in public or shared deployments.

Limits: even matching token prefixes may fail eligibility checks; semantic
hash stability is necessary but not sufficient for APC. Hardware and
runtime behavior require a real Apple Silicon test.
