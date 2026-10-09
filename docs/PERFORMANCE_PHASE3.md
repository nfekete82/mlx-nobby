# Performance Phase 3: native image job and service-handoff timings

This change adds **measurement only**. It does not change the 90% memory
admission threshold, model choices, GPU cache limits, runtime coordination,
queue retries, or any generation parameters.

For image jobs, the agent queue response can expose:

- `service_dispatch_wait_ms`: wall-clock duration from queue insertion to native
  service accepting the job. Includes `waiting_for_service` retries and
  scheduling; not exclusively resource handoff.
- `performance_timings.resource_wait_ms`: native job thread start until
  acquiring the image runtime lock / resource coordination.
- `performance_timings.preparation_ms`: runtime acquired until entering the
  generation/edit/upscale operation.
- `performance_timings.execution_ms`: all image edit/generate execution
  including model subprocess startup, prompt work, image output and any
  provider postprocessing. **Not** just denoising or model load time.
- `performance_timings.finalization_ms`: operation completion to job cleanup.
- `performance_timings.total_ms`: native job lifetime.

All native durations use monotonic clock; the agent service-dispatch delay
uses queue timestamps from one host. Intervals are best-effort and do not
claim to be model-weight loading, Metal memory, or network timings. An
interrupted/failed job can contain null phases. No prompts or local source
paths are added to the timing payload.

## Inspect a completed job

Using the agent job ID already visible in Nobby or the job API:

```sh
curl -fsS http://127.0.0.1:8010/media/jobs/image/JOB_ID | \
  jq '{status, service_dispatch_wait_ms, performance_timings}'
```

If the agent uses a different route, inspect the known existing job response
in DevTools; don't assume a new endpoint is created by this PR. Native image
jobs can be inspected at `http://127.0.0.1:8030/jobs/NATIVE_JOB_ID`.

Run `./scripts/mlx test-release` on the feature branch, then test one real
Nobby image edit. Compare phase breakdowns from multiple sequential jobs
before proposing any runtime optimization.
