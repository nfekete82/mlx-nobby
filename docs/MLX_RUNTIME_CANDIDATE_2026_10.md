# MLX runtime 2026-10 candidate (not production-approved)

## Candidate pins

| Package | Production baseline | Isolated candidate |
| --- | --- | --- |
| mlx | 0.32.2 | 0.32.2 |
| mlx-lm | 0.31.3 | 0.32.0 |
| mlx-vlm | 0.6.17 | 0.7.8 |
| transformers | 5.17.0 | 5.17.0 |

These pins are candidates for the release **after** v1.11.0. They update
`requirements/runtime.txt` for isolated validation only. This change does
not activate new weights, download models, alter LaunchAgents, replace
`runtime-venv` on the user's machine, or modify RAM/lease policies.

Upstream PyPI publication: MLX-LM 0.32.0 on 2026-10-01, MLX-VLM 0.7.8
on 2026-10-13. Recent upstream releases do **not** demonstrate faster
inference or feature compatibility on the user's Qwen3.8 checkpoint.

## First gate: dependency/API inspection on a Mac

Use a *new* virtual environment, never the existing live `runtime-venv`.
When normal Nobby inference is idle:

    python3.13 -m venv "$HOME/.local/share/mlx-nobby/runtime-probe-0-7-8"
    "$HOME/.local/share/mlx-nobby/runtime-probe-0-7-8/bin/python" \
      -m pip install -r requirements/runtime.txt
    "$HOME/.local/share/mlx-nobby/runtime-probe-0-7-8/bin/python" \
      -m pip check
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    "$HOME/.local/share/mlx-nobby/runtime-probe-0-7-8/bin/python" \
      -c 'import mlx.core, mlx_lm, mlx_vlm; print("imports ok")'
    "$HOME/.local/share/mlx-nobby/runtime-probe-0-7-8/bin/python" \
      -m mlx_vlm server --help

Check the server supports Nobby's flags `--model`, `--host`,
`--port`, `--prefill-step-size`, `--max-num-seqs`,
`--enable-thinking`, and the selected optional DFlash2 flags
`--draft-model` and `--draft-kind`. A CLI option's presence alone
does not establish that the feature works.

## Real A/B acceptance required before merge

Benchmark the same Qwen3.8 checkpoint in an isolated, safe, serial
configuration. Never run another heavy 27B model simultaneously with
production at 48 GiB merely to compare performance. Respect the existing
memory headroom and first unload/restore only through approved, idle service
procedures; if a safe configuration is unavailable, stop the evaluation.

1. Measure first semantic token (TTFT), long-response tokens/sec, total
   latency, prompt prefill, end-to-end real chat, RAM/swap and repeated-turn
   memory behavior for the **current** pins.
2. Repeat with the candidate pins at identical parameters. Check text,
   image understanding, coding, tool-calling, cancellation and streaming.
3. Compare normal decoding to the already-cached DFlash2 **only** if
   target+draft checkpoint compatibility, weight completeness and the
   upstream CLI contract are confirmed. Compare acceptance rates, short-
   and long-answer latency, output fidelity and peak memory.
4. Test `./scripts/mlx test-release` and real local acceptance with the
   proposed library stack.
5. Never loosen the 90% admission limit, service memory reserve or runtime
   lease to make a benchmark look faster.

Rollback: do not replace the live environment before the above gates pass.
If a candidate environment fails, keep the existing pinned runtime
untouched. The user can delete the *isolated* probe environment later.

## Separate upgrades

MLX-Audio 0.5.9 is available, but speech lives in `speech-venv` and has
its own pinned `transformers` constraint. Validate it in a separate PR
with German speech, TTS voices, STT/WER and latency regression checks.
MFLUX 0.22.0 and MLX Core 0.32.2 are already pinned to the verified
versions from the earlier audit.

## Product version

The pending product release is v1.11.0 (PR #208). Runtime dependency
pins are **not** the product's `VERSION` file. This experimental PR
does not bump `VERSION` or README prematurely. After real acceptance,
record the upgrade in `Unreleased` and prepare v1.12.0 in its normal
release-metadata PR.
