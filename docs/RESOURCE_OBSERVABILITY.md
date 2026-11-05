# MLX-Nobby resources: advisory dashboard extension

The existing native `runtime_coordinator` remains the **only scheduler** for
image/video RAM admission, model handoff and cross-service leases. The already
deployed Qwen3.5-4B Memory Supervisor remains responsible only for its own
port-8011 child process. **No new model controller or background process** is
introduced by this change.

## Performance Observatory

Open **System settings → Performance Observatory**. The existing performance
panel now shows a fourth local runtime: **Memory 4B**. It displays the
supervisor state and whether resource-pressure paused extraction, next to
Chat/Image/Video. It does not claim live token generation for the 4B process
without a measured inference counter.

The Unified Memory column now includes two short **advisory RAM estimates**:
Image and Video. Both reuse the already available snapshot from the media
queue/runtime coordinator, including their configured workload memory
reserves, 90% hard-admission limit and media headroom thresholds.

- *Headroom adequate (estimate)*: snapshot indicates no extra release is
  necessary to reach the configured budget. It **does not** guarantee a
  successful model load or generation.
- *Release other models first*: the projected model load would exceed the
  budget or the coordinator recommends releasing optional runtimes.
- *Admission cannot be estimated*: macOS did not return usable free-memory
  telemetry; **never present missing measurements as zero**.

Actual model admission/handoff happens only in the existing media runtime.
The dashboard is **read-only** and never starts, restarts or stops a model.
The system also already provides energy readings from macmon, including
GPU power in watts. Those are not a measured GPU-utilization percentage
and should not be mislabeled as such.

## Privacy and efficiency

No prompts, chat text, private paths, original memory files or in-flight
image/video parameters are included. The 4B model is named using a fixed
non-sensitive label; unrecognized supervisor states are not echoed.
No new macOS memory_pressure/sysctl calls are required per dashboard refresh:
the existing cached queue memory snapshot is reused.

## Measured model handoff timings

The next-stage instrumentation adds **measured elapsed times** without changing
scheduler policy, model load reserves, 90% hard admission or the safeguards
around active jobs.

- Native image jobs persist a bounded, allowlisted `runtime_handoff` record
  with scheduler lease wait, wait for video, speech/MuseTalk release, chat
  shutdown, preflight total and (once restoration finishes) chat restart.
  The existing Performance Observatory aggregates these numbers into
  sample counts, p50 and p95, and shows a new image handoff breakdown.
  Missing stages remain **unmeasured**, not zero.
- The optional 4B supervisor records API-ready after process start,
  process-unload duration and post-media recovery duration. These are
  bounded metrics held only in the supervisor's current-session state,
  refreshed with its normal heartbeat; they are **not** evidence of actual
  inference completion. The runtime card shows measured p50/p95 and
  sample counts, not fabricated estimates.
- The 4B sample window is at most 32 values per metric. It resets when
  the supervisor restarts, unlike the durable image/video job history.

### Why no aggressive automatic keep-warm yet?

Most native image jobs deliberately ask for exclusive models and chat
shutdown. This is a safety constraint on an Apple unified-memory machine.
Removing it based on an estimated amount of free RAM risks swap growth and
failed SDXL/Qwen-Edit generation. Handoff and model-readiness timing should
first be measured on real workloads; only then should a targeted opt-in
optimization be benchmarked against the existing reliable baseline.

## Deployment

A PR merge updates GitHub only. The **web frontend must be rebuilt** and
the **native Agent reloaded** to see this update in the local UI. First
inspect the local Git state and preserve the already-running Memory Supervisor,
private SQLite data and active media jobs. Use the repository's normal
versioned deployment helper only at a safe idle point and after a verified
local backup. No memory migration or backfill is needed.

Tests: `tests/test_resource_advisor.py`,
`tests/test_performance_observatory.py`,
`tests/test_performance_observatory_ui.mjs`.
