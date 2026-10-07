# LTX runtime patches — 0.16.0

This directory belongs exclusively to upstream commit
`90f76c20864ea612071afbb4e714ceea99e38e34` (ltx-2-mlx 0.16.0).

No local runtime patches are applied to this pin. The production Talking Photo
path was validated against the vanilla 0.16.0 runtime, including cloned voices.
The empty series is intentional: `scripts/apply-runtime-patches.py` still
verifies the exact upstream commit and fails closed on unexpected runtime
changes before `uv sync --frozen` runs.

The historical 0.15.12 patch series remains in its commit-bound directory and
must never be reused against this pin.
