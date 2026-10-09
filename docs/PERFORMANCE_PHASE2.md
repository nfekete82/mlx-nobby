# Performance Phase 2: image-edit baseline

**Scope:** measurement before tuning. Existing 90% memory admission, chat/video
headroom, timeout and process limits are not modified.

Qwen Image Edit 2511 was confirmed working end-to-end via MLX-Gen 0.38.0.
The first manual sample used 4 steps at 512×512 and reported 18 seconds in the
generation progress bar. That number is **not** comparable to whole-job Nobby
latency and cannot establish cold-start performance.

## Run locally

Only when no chat/video/image generation is active:

```sh
cd ~/mlx-web
python3 scripts/benchmark-image-edit-mlxgen.py \
  --image artifacts/image-edit-test/source.png \
  --samples 2 --steps 4 \
  --output-dir artifacts/performance/image-edit-baseline
```

The source is the existing synthetic 512×512 orange-tree test. The runner is
`~/.local/share/mlx-gen-venv/bin/mlxgen`. The command enforces Hugging Face
offline mode and does not start/stop any Nobby service.

To compare the existing low-RAM option, **only after confirming sufficient
memory and idle services**, run the same benchmark with
`--low-ram --output-dir artifacts/performance/image-edit-lowram`.
Do not run these benchmarks concurrently, do not change model weights, and do
not disable Nobby memory admission to improve benchmark numbers.

## How to interpret

- `wall_seconds`: subprocess duration, including Python startup, weight load,
  prompt encoding, and denoising.
- `peak_runner_rss_gib`: sampled parent-process RSS, **not** unified GPU
  memory, swap, or descendant RSS. Do not infer true Metal peak from it.
- `last_progress`: best-effort tqdm completion from the local diagnostic log.
- A second invocation may load weights again; consecutive subprocesses do not
  prove a model has remained in memory.
- Nobby's `waiting_for_service` time is **outside** this subprocess benchmark.
  Measure separately with the existing job APIs before attributing slowness to
  MLX-Gen.
- `summary.json` excludes prompt, image bytes, and source paths; per-run
  `edit-XX.log` files are local and may include raw provider diagnostics.
  Do not post log files without checking for private details.

Follow-up optimizations should be selected from actual measurements:
1. Confirm the p50 of local subprocess end-to-end time at identical settings.
2. Separately measure Nobby preflight/service-handoff latency.
3. Only then trial lower-overhead options one at a time; repeat identical input.
4. Re-run `./scripts/mlx test-release` and real Nobby image edit before merge
   of any production optimization.
