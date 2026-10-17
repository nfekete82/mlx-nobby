# Hybrid repeatability soak (opt-in only)

Goal: confirm repeatability of the existing **strict long-form correctness gate** across
4K/8K nominal-context synthetic dialogues before considering a new default.
The existing quality runner checks three exact marker values, long-form terminology,
real APC exact hits, memory headroom, and at most 1 GB swap growth per profile
workload. This harness executes both DFlash2 and Hybrid, alternates mode order
between rounds, stops on the first quality failure and restores the default profile.

## Local Apple Silicon run

Only when no chat/media jobs are active:

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/test/hybrid-soak-guardrails
./test-venv/bin/python -m pytest -q \
  tests/test_validate_hybrid_soak.py \
  tests/test_validate_hybrid_longform.py \
  tests/test_validate_hybrid_correctness.py \
  tests/test_hybrid_apc_dflash_runtime.py
./runtime-venv/bin/python scripts/hybrid_apc_dflash_runtime.py --check-only
./scripts/mlx chat-profile status
./scripts/mlx memory

python3 scripts/validate-hybrid-soak.py \
  --rounds 2 --context-sizes 4000,8000 --timeout 300 \
  --output /tmp/nobby-hybrid-soak-2rounds.json

./scripts/mlx chat-profile status
./scripts/mlx memory
```

Each round has **four complete synthetic two-turn tests**. Rounds start with
DFlash2 then Hybrid, and alternate on the next round. The runner saves only
metrics, marker booleans, and memory snapshots; never generated model text.
The output file is created with mode 0600 and cannot overwrite an earlier run.
Choose a new output name for subsequent runs.

**Stop / no-go:** any strict recall or cache-hit failure, non-normal pressure,
insufficient memory headroom, excessive swap growth, idle-check failure, or failed
server restart. Inspect `./scripts/mlx chat-profile status` after an error.
If automatic rollback fails, use `./scripts/mlx chat-profile default` only
after confirming the model server and agent are healthy and no jobs are active.

## Interpretation

Do not conflate tests passing with semantic numerical equivalence:
the check captures only the initial visible text and fixed synthetic markers.
Context sizes are estimates; output token counts are not accurately inferred
from character lengths. Alternating order reduces but cannot remove memory,
thermal and system-load effects. Snapshots miss transient unified-memory peaks;
a multi-hour concurrency/media stress test remains an independent gate.

**Do not enable Hybrid as production default solely from this soak.**
