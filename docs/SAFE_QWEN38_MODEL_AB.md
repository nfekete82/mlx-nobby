# Sequential Qwen model A/B (opt-in)

This is a deliberately constrained **local Apple Silicon** experiment. It is
not a production self-tuner, not a recommendation to switch a default model,
and not a Strata/GGUF integration.

## Purpose

Compare the **currently running 6-bit model without DFlash2** against the
**already-configured 4-bit SPECULATIVE_TARGET with the locally cached DFlash2
drafter**. The models are loaded sequentially, never concurrently. Before
starting, the script requires:

- Original chat profile is `default`, the loaded model matches `MODEL`, and
  neither APC nor draft flags are active.
- The candidate exactly matches the pre-existing `SPECULATIVE_TARGET`, and
  both candidate and configured `SPECULATIVE_DRAFT_MODEL` have local
  `config.json` files. No alternative 4-bit checkpoint is silently substituted.
- Agent observatory confirms all chat/media runtimes, media queue and lease idle.
- macOS memory snapshot shows `pressure=normal`, at least **25% free**
  and at least **8 GiB headroom**. When more than 10 GiB swap is allocated,
  the runner additionally samples `vm_stat -c 2 3` and requires **zero
  new swapouts over that three-second interval**. Missing or malformed
  activity counters fail closed. Memory is rechecked at phase boundaries.

The macOS runtime memory guard is *also* applied by the existing `mlx restart`.
No condition above bypasses it. Historical swap occupancy alone does not
prove active thrashing; recent swapouts, elevated pressure or insufficient
headroom still block the experiment. This additional check does not weaken
the real runtime guard. A short quiet interval is not proof that subsequent
model loads will remain free of memory pressure.

## Read-only readiness plan (safe to run now)

```bash
cd ~/mlx-web
python3 scripts/benchmark-qwen38-model-ab.py
```

Shows configured models, memory data, optional three-second swap-out
activity and any blockers. It does not change config, load weights or restart
services. Even when `ready: true`, run an experiment only on an idle Mac.

## Explicit real experiment (only when plan is ready)

```bash
python3 scripts/benchmark-qwen38-model-ab.py \
  --confirm-restarts --samples 3 --timeout 300 \
  --output /tmp/nobby-qwen38-model-ab-1.json
```

A complete quality comparison is *optional* but recommended before concluding
that a candidate is better:

```bash
python3 scripts/benchmark-qwen38-model-ab.py \
  --confirm-restarts --samples 3 --timeout 300 --with-quality \
  --output /tmp/nobby-qwen38-model-ab-quality-1.json
```

The quality option runs the existing frozen **48-case** quality suite once for
each model, then uses its existing deterministic `compare` function. Four cases
still require human assessment. The benchmark itself writes no raw chat
responses; intermediate synthetic quality summaries are held in a private
temporary directory. Final JSON is created exclusively with permission 0600
and cannot overwrite existing files.

Speed workloads are the existing `long` and `coding` fixed prompts from
`benchmark-chat-latency.py`, with output caps of 384 and 512 tokens
respectively. Each run reports end-to-end median/p95, server generation
tokens/s when available, completion token counts and stop reasons. Different
checkpoints/tokenizers can produce different lengths, so speed alone cannot
prove equivalent work or answer quality.

**Restoration:** The entire pre-experiment config text is restored on ordinary
success, Python exception or SIGINT/SIGTERM, followed by a chat-server-only
restart and model identity verification. The Agent and image/video services are
not restarted. When the config changed externally, the script refuses to
overwrite it. Process kill -9, power loss, OS failure or a failed memory guard
during recovery cannot guarantee restoration; inspect
`~/.config/mlx-server/config`, `mlx serverargs` and `mlx agent status`
in that case. Run when the system is otherwise unused.

## Local CPU tests

```bash
python3 -m pytest -q tests/test_benchmark_qwen38_model_ab.py
python3 -m py_compile scripts/benchmark-qwen38-model-ab.py
```

These tests mock the runtime and do not perform actual Apple Silicon inference.
A real 4-bit/DFlash2 improvement is **not yet measured** and requires running
the experiment on the Mac.
