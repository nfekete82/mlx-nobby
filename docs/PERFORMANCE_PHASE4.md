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
