# LTX runtime patches

This directory belongs exclusively to upstream commit
`1724ca673d59f023a8a95efee06e5d36d61c2765` (ltx-2-mlx 0.15.12).
`0001-extend-lowram-lora-targets.patch` adds generic non-block LoRA fusion
for the streaming loader: timestep MLPs, modulation, input projections and
raw output tables. Existing block indexing and bind-time fusion are preserved.
Every pair is validated for target, complete A/B, rank, shape and floating
dtype before fusion. Scaling follows the existing fuser (`B @ A * strength`);
alpha metadata is not separately normalised, matching the block path.

Resident targets are fused on a freshly loaded model, one target at a time.
Each result is evaluated before loading the next target, and consumed root
A/B references are released. Blocks remain streamed; no full-model delta
set or second materialised checkpoint is created. Failed models are not
returned to the pipeline; the Nobby worker discards failed pipelines.
The standard/no-adapter dispatch remains unchanged.

The patch includes numerical MLX tests for all four target classes, mixed
block/root adapters, multiple sources, invalid pairs and failure isolation.
Run the upstream `tests/test_non_block_loras.py`, `test_block_streaming.py`,
`test_pending_loras_dispatch.py` and `test_lora_renaming_map.py` using the
patched checkout's source packages and a Python environment with MLX/pytest.
Repository CPU tests also exercise application/idempotency/fail-closed state
using the shipped patch's exact hunk contexts without requiring model files.

Future `0001-*.patch`, `0002-*.patch` files are applied in lexical order by
`scripts/apply-runtime-patches.py`, after the exact checkout and before
`uv sync --frozen`. The helper validates the entire series using a disposable
Git index before changing the worktree. It derives the expected Git tree from
the actual patch contents, without trusting a marker. Repeated installation
accepts only the clean pin or the exact expected, unstaged patch state.
Unrelated changes, staged changes, partial application, wrong pins and
non-applicable patches fail closed. Ignored installation data such as `.venv`
is outside the managed Git tree; nonignored untracked files are rejected.

An upstream upgrade requires explicitly rebasing and validating the series in
a directory named for the new full commit hash. Patches are never adapted,
repaired, applied with three-way merging or reused against another pin.
