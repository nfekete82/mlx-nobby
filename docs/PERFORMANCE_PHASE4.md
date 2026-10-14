# Performance Phase 4: MLX-Gen provider timing

This PR **measures** the MLX-Gen subprocess, rather than changing model
settings or claiming faster generation. It preserves Nobby's 90% memory
admission, 24 GiB process cap, low-RAM mode, service cancellation and timeout.

A finished native image-edit job on port 8030 now exposes:

```json
{
  "performance_timings": {
    "resource_wait_ms": 0,
    "execution_ms": 0
  },
  "provider_timing": {
    "schema": 1,
    "process_wall_ms": 0,
    "exit_code": 0,
    "steps": 4,
    "width": 512,
    "height": 512,
    "low_ram": true
  }
}
```

Numbers above are **illustrative placeholders**, not measured results.
Agent media jobs mirror `provider_timing` in their existing job response.
The payload stores no prompt, file paths, image contents or stack traces.
It is available after an actual image edit, not historical jobs.

Compare `performance_timings.execution_ms` and
`provider_timing.process_wall_ms` from the **same** job. Their difference
includes non-subprocess work; it does **not** reveal precisely how long
weights load or GPU denoising takes. Phase-4 follow-up is an opt-in diagnostic
that isolates model-loading and per-step time, once supported without
disabling memory protections or collecting user prompts.

Before proceeding, test with `./scripts/mlx test-release` and a real
Qwen Image Edit. Reproduce timings with the same step count and resolution.
Do not compare the existing 512×512 4-step synthetic benchmark directly to
a higher-resolution real image edit.

## Phase 5: MLX-Gen cold-process diagnosis (no runtime tuning)

Each completed MLX-Gen image-edit job now adds three *content-free* observations
to the existing `provider_timing` object:

- `process_spawn_ms`: time spent in `subprocess.Popen`; does **not** include
  subsequent Python imports, model loading, or diffusion.
- `first_output_ms`: best-effort time from process launch until the first
  nonempty stdout/stderr output is observed, or `null` when the child is silent.
  Output may be startup logs and is **not** a weight-load completion marker.
- `fresh_process: true`: documents that each edit launches a new isolated
  MLX-Gen process. It does **not** indicate whether model weights were served
  from the filesystem cache.

All timings exclude prompts, paths, image data and logs. The parent still
uses isolated process groups, unchanged cancellation/timeout polling, the
existing **24 GiB process RSS cap**, **90% RAM admission** and model handoff
policies. No warm worker or extra model residency is introduced.

The experiment is to collect at least three sequential edit jobs of the same
model, resolution, step count and prompt length (while the system is idle),
then compare `process_wall_ms`, `process_spawn_ms` and
`first_output_ms` with the native `performance_timings.execution_ms`
and queue wait. Identify whether repeated subprocess startup/preparation
is materially expensive before considering a resident image worker.

Any later warm-worker prototype needs strict single-job serialization,
finite idle expiry, RAM admission before reuse, cancellation, crash recovery,
and a clean handoff to video; this PR makes **no such behavior change**.
