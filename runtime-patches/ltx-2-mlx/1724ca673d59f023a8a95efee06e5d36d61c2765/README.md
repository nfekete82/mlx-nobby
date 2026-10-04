# LTX runtime patches

This directory belongs exclusively to upstream commit
`1724ca673d59f023a8a95efee06e5d36d61c2765` (ltx-2-mlx 0.15.12).
The current series is empty; it does not change the runtime or LoRA loader.

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
