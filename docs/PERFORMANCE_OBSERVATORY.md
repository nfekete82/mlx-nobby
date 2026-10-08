# Performance Observatory

Open **Settings → System → Server** (route `/settings/advanced/server`). The
read-only panel complements [System Health](SYSTEM_HEALTH.md) with live local
model/media measurements and unified-memory estimates.

## Measurements and limits

- Model calls: TTFT, throughput, queue wait and timing summaries from existing
  content-free observability traces. Model history lasts for the agent process.
- Media: recent image/video/Shorts jobs, generation/queue/total timings and
  supplied warm/cold-start metadata from durable queue history.
- Video resource handoff: successful native video-job preflight records
  `runtime_handoff.duration_ms` from the request's entry into the coordinator
  (including the lease wait) through memory admission. The stage timings in
  `runtime_handoff.timings_ms` distinguish lease waiting, idle image/speech/
  MuseTalk release, and chat stop where invoked. They do **not** measure LTX
  model loading or total video generation. A false/missing stage means it was
  skipped, not zero milliseconds. The Agent mirrors this content-free record
  into durable queue history; the Observatory displays per-job handoff
  duration, p50/p95 and the number of completed videos that released chat.
  Old records lacking timing data remain unknown, not zero.
  The breakdown below the live runtime cards now shows per-stage p50/p95 for
  lock wait, image/speech/MuseTalk release and chat stop, with sample counts.
  A skipped stage is unknown (not 0ms), and these stages do not sum to total
  elapsed time because RAM snapshots, health checks and other overhead also
  contribute. The image-release flag previously counted already-unloaded image
  models as "released"; this is corrected for new `runtime_handoff.version=2`
  jobs. Older records contribute to timing summaries, but their image-release
  count is deliberately excluded rather than misrepresented.
- System: memory budget, available/headroom estimates, pressure, swap, loaded
  runtime state and the current coordinator lease. Repeated read-only
  diagnostic requests coalesce into one macOS memory_pressure/sysctl probe,
  sharing the estimate for up to 1.5 seconds; Observatory reuses the queue's
  snapshot rather than probing again. **This diagnostic cache is never used
  for model-load admission or image/video handoff checks**, which still sample
  memory directly before making safety decisions.

Native video generation keeps live in-memory progress visible at full update
frequency, but coalesces progress-only disk syncs to at most approximately one
every 1.5 seconds (configurable with `MLX_VIDEO_PROGRESS_PERSIST_SECONDS`).
State, phase changes, errors and terminal results remain durable immediately.
Native video RAM/swap telemetry is sampled no more frequently than every two
seconds during generation, plus the initial and final snapshot. Consequently
`memory_peak` is a sampled estimate, not a guaranteed instantaneous hardware
peak. These intervals do **not** govern admission: video model-load and runtime
handoff RAM safety checks continue to use fresh memory measurements.

Unknown/nonfinite values are omitted from metric series, not treated as zeros.
Series include count, latest, average, p50/p95 and min/max; this endpoint uses
linear percentile interpolation. A runtime marked warm indicates observed
loaded state, not a universal latency guarantee. Estimates and small samples
must not be presented as native measured token counts or a complete Metal-memory
accounting. The [performance audit](PERFORMANCE_AUDIT.md) is a dated measurement
report, not a guarantee for the currently selected model or host.

The UI refreshes automatically only when its settings panel and browser document
are visible, coalesces overlapping refreshes, and refreshes when opened. It does
not change model selection, runtime scheduling, quality or job state.

## Local API

- Agent: `GET /api/performance/observatory?limit=40`
- Web: `GET /api/mlx/performance/observatory?limit=40`

Limit is clamped to 1–100. The response contains `ok`, `version=2`, `captured_at`,
`model`, `media`, `system={memory, runtimes, runtime_lease}` and retention notes.
`version=2` describes this diagnostic response schema, not the Nobby release
or the OpenAI-compatible `/v1` API.

Implementation: `agent/performance_observatory_routes.py`,
`backend/performance_observatory_routes.py`, `backend/observability.py`,
`runtime_coordinator.py`, `frontend/assets/chat/performance-observatory.js`.
Tests: `tests/test_performance_observatory.py` and
`tests/test_performance_observatory_ui.mjs`.
