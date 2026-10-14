# MFLUX Qwen Image 2.1 Edit: Subprocess diagnosis

The October 14 local Observatory history had 46 Juggernaut XL jobs (median
31.6 seconds), 10 Osaurus Qwen Image 2.1 Edit jobs (median 72.0 seconds),
four MLX-Serve Qwen Image 2.1 jobs (median 81.6 seconds) and one FLUX job.
These are historical observational medians, **not matched settings**.

## What this patch measures

The existing `provider_timing` callback is extended to isolated subprocess
invocations of the MFLUX `qwen-image21-edit` family, including
`mflux-osaurus-qwen-image-2.1-edit`. It records:
- `process_wall_ms`: subprocess duration including model initialization,
  image processing and finalization; it does **not** isolate model weight load.
- `process_spawn_ms`: time for `subprocess.Popen` using an independent
  `perf_counter` clock; no change to timeout accounting.
- `first_output_ms`: best-effort first observed stdout/stderr activity,
  or null if the subprocess emits no output. This is **not** a model-load
  completion or first GPU denoising event.
- `provider="mflux"`, `fresh_process=true`, `low_ram` and
  `mflux_cache_limit_gb` derived directly from actual subprocess CLI flags,
  not from estimates or user prompts.

MFLUX command arguments and model settings are **unchanged**. No warm-worker
residency, quantization change, cache increase or concurrency change is made.
The existing RAM admission, 24-GiB RSS process guard, timeout, process-group
cancellation and media handoff rules remain active.

## Controlled comparison

Once this patch has passed CI, merged and the updated image-service code is
running on the Mac, perform three sequential Qwen 2.1 Edit jobs with the
identical input images, prompt, dimensions, steps, guidance and seed, while
other heavy media jobs are idle. Use the Observatory's latest per-job timing
fields (or the model-filtered report from PR #220 once merged), and compare
startup/spawn, total provider wall-time, low-RAM flag and applied MLX cache limit.

Do not infer that a worker would save all of `process_wall_ms`, or that the
observed Juggernaut/Qwen median difference is caused by loading. A resident
worker is a later **separate** opt-in experiment after we have phase timings,
memory pressure evidence, crash/cancel safeguards and a meaningful baseline.
