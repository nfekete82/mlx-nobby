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
  count is deliberately excluded rather than misrepresented. During a new
  video handoff, a loaded idle image runtime may remain resident only when a
  fresh, complete and finite macOS memory estimate reports normal pressure,
  at least the configured video headroom and sufficient projected RAM below
  the existing model-load hard limit. The check happens after active image
  work finishes and is repeated immediately afterward. If either sample is
  missing/unsafe, the coordinator uses the established image-unload path.
  Already-cold models are neither unloaded nor counted as preserved. New
  video jobs record `image_preserved` separately from `image_released`.
  This avoids unnecessary reloads for a subsequent image job, but does not
  guarantee faster LTX inference or permit overcommitting unified memory.
- System: memory budget, available/headroom estimates, pressure, swap, loaded
  runtime state and the current coordinator lease. Repeated read-only
  diagnostic requests coalesce into one macOS memory_pressure/sysctl probe,
  sharing the estimate for up to 1.5 seconds; Observatory reuses the queue's
  snapshot rather than probing again. **This diagnostic cache is never used
  for model-load admission or image/video handoff checks**, which still sample
  memory directly before making safety decisions.

The unified media queue retries HTTP 409 (busy) or 503 (service unavailable)
during native job creation with a bounded 1.5–30 s backoff. While waiting,
an older job keeps priority **within its own kind**, but jobs of another kind
may run if no native job is active. Retry deadlines are persisted across Agent
restarts and do not appear as an extra model load. Once a native job has been
dispatched, the single worker continues following that job until it finishes;
it does not start competing heavy jobs merely because the native service's
status endpoint is temporarily unreachable. This maintains one heavy native
generation at a time and avoids unintentional concurrent Metal allocations.

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


## Opt-in local chat latency baseline

For a controlled latency comparison on a running Mac, use the read-only
`scripts/benchmark-chat-latency.py` probe. It sends a short deterministic
request to an **already selected and loaded** model. It does not explicitly change the selected model, restart runtimes, download
weights, or manipulate swap; the inference endpoint may lazily load the
specified model. Ensure the intended model is already loaded beforehand. Run only
when the service is idle and you consent to short inference requests.

```sh
python3 scripts/benchmark-chat-latency.py \
  --url http://127.0.0.1:8000 \
  --model "/absolute/path/to/your/loaded/model" \
  --samples 5 \
  --output artifacts/performance/chat-baseline.json
```

The first sample is reported separately; subsequent samples have interpolated
p50/p95 statistics for measured end-to-end latency and server-provided prompt
and generation timings (when available). The **first call is not necessarily
cold** and the benchmark **does not establish why** it may be slow. Missing
timings are absent, never zero. No prompts or responses are persisted.
Optional JSON output remains local under ignored artifacts. This probe does
not currently capture TTFT (non-streaming endpoint), model-load duration,
RAM or swap, nor does it reproduce image/video handoff. It is a narrow baseline
to be paired with the existing Observatory's runtime and memory history.
Do not use the benchmark to justify lifting admission reserves or timeouts.
