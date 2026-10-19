# Per-turn hybrid cache miss diagnosis

Purpose: explain the reproducible baseline from the Mac:

| Turn | Exact hits added | Matched tokens added |
| --- | ---: | ---: |
| 1 | 0 | 0 |
| 2 | 1 | 324 |
| 3 | 0 | 0 |

The normal terminal benchmark stays unchanged. This branch adds a separately
opt-in runtime probe and `--diagnose` reader. It logs numeric token-prefix
metadata and reasons, never token values, prompts or generated text.

## Enable on macOS launchd, run and disable

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/diag/chat-cache-turn-miss

./test-venv/bin/python -m pytest -q \
  tests/test_benchmark_chat_cache.py \
  tests/test_chat_cache_turn_diagnostics.py \
  tests/test_hybrid_cache_diagnostics.py \
  tests/test_hybrid_apc_dflash_runtime.py

./runtime-venv/bin/python scripts/hybrid_apc_dflash_runtime.py --check-only
launchctl setenv NOBBY_HYBRID_CACHE_DIAG 1
./scripts/mlx restart
./scripts/mlx benchmark chat-cache --diagnose --json-out /tmp/chat-cache-diagnosed.json

# Return to normal mode after the capture.
launchctl unsetenv NOBBY_HYBRID_CACHE_DIAG
./scripts/mlx restart
```

The **LaunchAgent**, not merely the calling shell, must receive the variable.
If no per-turn diagnostic records appear, check the process environment and
`~/.config/mlx-web/server-error.log`. The benchmark prints an explicit
missing-record message rather than claiming a reason.

The diagnostic compares each current token prefix with just the last
successfully stored checkpoint in the model process, and reports the
semantic-hash equality and common-token count. It does not prove an
eviction when the prefix matches, and concurrent chat traffic can confuse
the sequence. Run with no other conversations.

Interpretation:
- `prefix_shorter_than_checkpoint`: current request diverges before the
  previous saved checkpoint (often chat-template or message mutation).
- `semantic_hash_changed`: semantic-hash eligibility changed.
- `lookup_miss_despite_matching_prefix`: inspect manager lookup constraints.
- `exact_hit`: a cache checkpoint was reused.
- Missing records: cannot infer the reason.

Important: the benchmark's default system prompt is empty. It exercises the
real web backend but is not guaranteed to match the full browser prompt.
No cache algorithm changes are made by this branch.
