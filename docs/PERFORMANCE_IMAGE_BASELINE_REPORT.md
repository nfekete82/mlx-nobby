# Image Edit Baseline: Real Nobby Jobs

This read-only report complements the CLI-only MLX-Gen benchmark and the
startup telemetry from PR #219. **It does not generate images or change model
residency.** It queries the existing local Performance Observatory exactly
once and writes a content-free JSON summary. The Observatory now includes a
strict numeric allowlist from completed image-job telemetry; no native job IDs
are sent to another service.

## Controlled local comparison

After PR #219 has passed CI, merged and its image service code has been deployed
to the actual service installation (normally `~/mlx-web`), complete three real
image edits in Nobby, sequentially, with:

- The same Qwen Image Edit model and source image
- The same prompt, image dimensions, step count, guidance and seed
- No concurrently active video, chat inference or other heavy media jobs

Then collect the full per-model summary and the three most recent
Juggernaut XL jobs:

```bash
cd ~/mlx-web
python3 scripts/report-image-edit-baseline.py \
  --model juggernaut-xl --samples 3 \
  --output artifacts/performance/juggernaut-baseline.json
```

For image editing instead, set `--model mflux-osaurus-qwen-image-2.1-edit`.
Omit `--model` for the three latest jobs regardless of model.

The report's `by_model` section summarizes **all available recent completed
image jobs (up to 100)** separately by model: count, median, p95, average for
total, generation and queue time. The detailed `samples` and `median_ms`
sections contain up to three recent jobs matching `--model`, plus available
content-free `provider_timing` and native `performance_timings`.
All missing values remain `null`, not zero. The report intentionally contains
no prompts, chat IDs, file paths, image bytes or job IDs.

Per-model historic groups can still mix resolutions, image operations,
step counts and guidance settings. These observational comparisons are useful
for prioritization, **not** apples-to-apples model speed benchmarks.
The script does not assert the last three jobs were identical; the operator
must control that manually.

If the image service is still using code from before PR #219,
`process_spawn_ms`, `first_output_ms` and `fresh_process` may be absent.
Restart only when existing image jobs are idle, after deploying changes to the
**service working directory**, not merely a separate Git worktree.

The existing CLI-only benchmark `scripts/benchmark-image-edit-mlxgen.py`
measures a different path; do not mix its wall time with end-to-end Nobby time.
Neither baseline alone proves that a warm worker will improve performance.

## Safety

The script makes one loopback HTTP GET request to the Observatory, does not touch images or jobs,
and does not alter RAM admission (90%), the image process cap (24 GiB), image
quality, backend settings, timeouts, or media lifecycle. Manual real edits still
use Nobby's coordinator and memory admission. Reports stay local.


## Juggernaut XL phase diagnostics

After deploying this change to the **native Image Service**, generate one new
Juggernaut XL image and run the same read-only command:

```bash
python3 scripts/report-image-edit-baseline.py \
  --model juggernaut-xl --samples 3 \
  --output artifacts/performance/juggernaut-baseline.json
```

New successful SDXL jobs report the following *local, best-effort* millisecond
measurements in `samples` and `median_ms`:

- `sdxl_model_prepare_ms`: model checkpoint loading, offload setup and scheduler selection.
- `sdxl_pipeline_setup_ms`: source/image prep and inference argument setup.
- `sdxl_first_step_ms`: inference start to first completed denoise callback.
- `sdxl_denoise_window_ms`: first callback to final callback; **excludes
  the first step** (not the entire denoising cost).
- `sdxl_decode_finish_ms`: final callback to pipeline return, approximately
  VAE decoding and post-denoise finishing; not a dedicated GPU benchmark.
- `sdxl_image_save_ms`: encoding and writing the PNG.
- `sdxl_worker_total_ms`: total native worker time after it parsed the request.
- `sdxl_worker_outside_ms`: extra time measured by the Image Service beyond
  the worker's own timing (process/Python imports, IPC and delivery); not
  exclusively GPU or model-load time.
- `process_wall_ms`: Image Service wall time starting before SDXL
  worker subprocess start; includes `sdxl_worker_total_ms` plus overhead.
- `fresh_process`: whether a new SDXL subprocess was spawned for the job.
- `sdxl_cold_model`: whether the SDXL model had to be loaded in that worker.

All old samples retain `null` for these fields. Do **not** mix old samples
with fresh instrumented jobs when drawing conclusions. The pipeline may
perform asynchronous MPS work, so timings are wall-clock boundaries, not
precise GPU kernel timing.

**Important safety behavior:** Normal SDXL generation deliberately shuts down
its worker before the shared coordinator restores the chat model. The SDXL
idle timeout by itself does not create warm reuse for these requests.
Changing that behavior would alter memory safety and requires a separate
performance + memory validation. This patch only adds timing events; it
changes neither CPU offloading, MPS watermarks, model residency, resolution,
steps, scheduler, nor image quality.

## Follow-up: Native post-provider latency (October 2026)

A fresh user-run **Juggernaut XL 1216×1216 / 40 steps** image reported:

- Total 36,272 ms; native execution 34,988 ms.
- Parent SDXL provider wall time 26,618 ms.
- Difference ~8,370 ms **not attributable to SDXL diffusion alone**.

Standard production `de.nobby.mlx-images` LaunchAgent sets
`MLX_IMAGE_QUALITY_UPSCALE=off`: the optional Real-ESRGAN Quality+
phase is **not** the expected source of that gap.

The native ImageJobTimings producer now reports an additional disjoint
execution breakdown, exposed through the allowlisted Performance
Observatory and existing read-only baseline script:

| Field | Boundary | Interpretation |
| --- | --- | --- |
| `render_setup_ms` | execute entry → output preparation callback | Native request resolution and setup |
| `provider_and_setup_ms` | preparation callback → saving callback | Provider processing, validation and optional enhancement (not pure diffusion) |
| `output_finalize_ms` | saving callback → final result ready | Output conversion, particularly PNG → WebP |
| `sdxl_unload_ms` | result ready → completed SDXL worker shutdown | CPU/MPS memory release before restoring chat |
| `runtime_return_ms` | SDXL unloaded → coordinator exit | Coordinator cleanup, **including** any chat restart |

For non-SDXL jobs, `sdxl_unload_ms` is null and
`runtime_return_ms` begins at result-ready. For older jobs or failed
jobs, absent stage values remain null.

Unlike the independent timings inside `sdxl_worker.py`, these events
measure the full native lifecycle around the provider. They partition
`execution_ms` on normal successful SDXL jobs without assigning time
to unverified causes. Neither job execution, routing, model settings,
checkpoint loading, memory budgets, safe shutdown, file encoding nor
visual image content changes.

After deployment, create **one fresh** Juggernaut XL image with the same
settings and run:

```sh
python3 scripts/report-image-edit-baseline.py \
  --model juggernaut-xl --samples 1 \
  --output artifacts/performance/juggernaut-baseline.json
```

If `sdxl_unload_ms` or `runtime_return_ms` accounts for most of the
8.37s, prioritize safe teardown/handoff optimization only after
evaluating memory-pressure constraints. If `output_finalize_ms` is
large, test JPEG/WebP encoding tradeoffs under equal visual quality.
If `provider_and_setup_ms` includes a large extra operation, inspect
the provider path before changing the step count.

## Early SDXL image preview during chat restoration

A measured 40-step 1216×1216 Juggernaut job took 44.61 seconds total.
Its native breakdown showed:

- 32.62 s provider and setup
- 0.16 s WebP finalization
- 0.49 s safe SDXL worker shutdown
- 10.21 s returning from runtime coordination (which includes chat restart)

The native image file is **fully encoded** and SDXL is safely **unloaded**
before the coordinator begins restoring chat. The UI may now receive an
*early, nonterminal* artifact while the job reports
`status=saving, phase=restoring_chat`. This makes the image viewable and
downloadable without waiting for the chat service to finish booting.

Safety and lifecycle details:

- Do **not** mark the job `completed` early. Agent queue and image-service
  locks remain active until the normal coordinator exit and all cleanup.
- Do **not** start another image edit, upscale, or generation from the
  early artifact while runtime handoff is in progress.
- Only a generated SDXL image with a successful render, finalized file,
  successful SDXL worker teardown, and no cancellation is exposed early.
  Image edits, upscaling, Qwen/MLX-Serve, and legacy jobs are unchanged.
- If the handoff fails or the job is cancelled, the provisional artifact
  is withdrawn and the existing failure/cleanup rules apply. The job is
  not presented as successful.
- No change to generation steps, MPS memory guards, offloading, model
  residency, task coordination, chat restart behavior, or image quality.
- On this specific measured run, the **perceived image-view latency**
  could improve by up to roughly 10 seconds, subject to polling/render
  overhead. The **total job duration is not shortened**.

Deployment requires a native Image Service restart, an Agent restart,
and a **web container rebuild** because the chat renderer and translations
are updated. Compare image-first-visible timing to final job completion.

## Juggernaut XL multi-variant batching — single safe runtime handoff

Before this optimization, `/jobs/variants` ran each Juggernaut XL image
through its own `image_runtime` handoff. A five-variant series therefore
repeated chat shutdown/restore, Python/torch worker startup, and checkpoint
initialization five times.

For **2 or more pending text-to-image variants of the same canonical
SDXL model**, the batch now:

1. Enters the standard exclusive `image_runtime` **once**, including the
   existing memory admission guard, service-idle checks and chat release.
2. Generates images sequentially with their original seed, prompt, quality
   profile and all settings preserved. The SDXL worker is reused while the
   lease is held. Each job retains fresh provider memory protection and
   `ensure_model_load_allowed` checks.
3. Publishes each completed variant and preserves normal per-image artifacts
   and failure/cancellation semantics. The batch-wide image lock remains held;
   no other heavyweight generation can overlap.
4. Always shuts down the SDXL worker **before** leaving the lease or
   attempting chat restoration, even if a variant fails or is cancelled.
   If that shutdown fails, the batch is marked failed and chat restoration
   is explicitly suppressed to avoid resident model overlap.
5. Restores chat at the end through the unchanged coordinator; its existing
   pressure/headroom checks can still skip unsafe restores.

Single-image generation, single pending variants, img2img/reference edits,
Qwen, upscaling, video jobs and local models other than SDXL follow their
existing paths. This does not change generated pixels or model step count.

**Expected but unmeasured benefit:** Removing repeated
SDXL startup (~4s in the last measured cold generation) and
chat handoff (~10s return in that run) could save several seconds
per additional Juggernaut variant. Actual gain depends on memory pressure
and the Mac's workload. Use one fixed-seed multi-variant A/B test and check
identical settings, result count and memory guard. No claim is made about
single-image latency (which is unchanged).
