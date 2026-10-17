# EXPERIMENTAL – APC + DFlash2 in a single MLX-VLM model server

**Prototype only. Do not enable in production or merge as the default.**

Target: **MLX-VLM 0.6.17**, Qwen3.8 local text generation, DFlash2 draft,
\`apc_mode == "exact"\`, **single request**. The main motivation is the verified
APC exact-cache hit that reduced a ~4k-token follow-up's first visible text
from 10.81 seconds (DFlash2 alone) to 0.83 seconds (APC alone), while
DFlash2 generates longer answers faster from a cold context.

This branch implements a *research adapter* for the separate DFlash2 prefill
path that would otherwise report \`cached_tokens=0\` even when APC is enabled.

## Architecture and guardrails

- **No edits to installed MLX-VLM**: the experimental launcher imports
  \`ResponseGenerator._run_speculative\` from the installed MLX-VLM, verifies
  source anchors and distribution version, compiles an augmented method **in
  memory**, and then invokes the original server CLI. The server still runs
  under Nobby's normal memory admission guard. On restart outside this
  profile, the upstream method runs unchanged.
- Hybrid \`apc\` + \`dflash\` is used only when one plain-text request is
  pending, the loaded model explicitly supports exact cache snapshots, and
  chunked prefill is supported. **Multimodal and multi-request batches use
  the unmodified upstream DFlash2 path.** The adapter will not attempt to
  turn recurrent Qwen3.8 SSM states into blockwise KV tensors.
- A cold query computes and stores a deep-copied exact snapshot before the
  final ~16 text tokens. For a matching follow-up, the adapter restores the
  cloned exact prefix and prefills only the suffix, preserving DFlash2's
  final-token hidden-state capture and subsequent decoding loop.
- APC stores remain in **RAM**, capped at **one exact-cache entry** and **512
  block slots**. This is *not* a byte-level limit. Actual unified-memory
  consumption needs measurement, especially with large contexts.
- \`default\` continues to mean *no changes* to the previously configured
  production runtime. This branch does not activate the experimental mode
  automatically.

### macOS prerequisities

Ensure the **Test CI** and **Chromium** checks are green first. Only on the
user's local Mac, once all media and chat work is idle:

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/exp/hybrid-apc-dflash-prefill
./test-venv/bin/python -m pytest -q   tests/test_hybrid_apc_dflash_runtime.py   tests/test_chat_performance_profiles.py   tests/test_chat_experience_benchmark.py

# Import + source-layout compatibility check only (no model reload):
./runtime-venv/bin/python   scripts/hybrid_apc_dflash_runtime.py --check-only

./scripts/mlx chat-profile status
```

If **all** those checks pass, and there is sufficient memory headroom,
the reversible three-way comparison can be considered:

```bash
./scripts/mlx memory
./scripts/mlx chat-profile compare   --include-hybrid   --context-sizes 4000   --samples 2   --max-tokens 384   --timeout 300

./scripts/mlx chat-profile status
```

This invokes three server restarts/sequential sets of synthetic model
inference and attempts to restore the starting profile even when interrupted.
No user prompts, user chat history or generated text is written to disk.
Profile management refuses switching when the Agent Observatory reports
active Chat/Media or an active runtime lease.

To examine the hybrid alone after validation:

```bash
./scripts/mlx chat-profile hybrid
./scripts/mlx chat-profile status
./scripts/mlx chat-profile default
```

**Before comparing raw performance** verify response correctness and ordinary
multi-turn chat behaviour. A correct model load and a positive `exact_hits`
counter alone do **not** establish that speculative decoding uses correct
hidden states after an APC restore. Also compare the full generated answers
manually against the individual APC and DFlash2 profiles. Examine RAM
pressure and swap *deltas*, not just APC's `resident_bytes`: exact-cache
memory is not fully reflected in the blockpool counters.

## Stop/rollback

Normal rollback:

```bash
./scripts/mlx chat-profile default
./scripts/mlx chat-profile status
```

If the Agent is down and the profile manager cannot safely read its runtime
lease, first stop the model server, remove only the experimental
`MLX_CHAT_PERFORMANCE_PROFILE` line from
`~/.config/mlx-server/config`, and restart with `./scripts/mlx restart`.
Do not edit other model/draft parameters or remove existing personal
configuration. A stopped or failed experimental process does not modify
the installed MLX-VLM package or weights.

## Explicitly not proven

- No end-to-end hybrid GPU results have been run as part of GitHub Actions.
  Github CPU-only tests validate syntax, anchors, the conditions for eligible
  requests and rollback plumbing, **not** Apple Silicon MLX execution.
- Equality/quality of model outputs after exact-SSM restoration remains
  **unverified** until local paired prompts are compared.
- Whether DFlash2 retains its full token/s advantage when snapshotting exact
  cache state remains unmeasured.
- The run order is fixed; thermal, memory, and queue state may skew single
  measurements. Repeat controlled tests before choosing a new default.
