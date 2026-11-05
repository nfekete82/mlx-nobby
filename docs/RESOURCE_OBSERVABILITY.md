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
