# Chat restore: measured readiness polling improvement

Date: 2026-11-06. Baseline: `3a2b3e5c` (PR #433). No production restart,
deployment, image inference or large model load was performed for this change.

## Critical path and meaning of the existing measurements

1. `agent/media_queue.py::_dispatch_and_poll` asks memory coordination to finish
   any active extraction before dispatching a heavy native job. A busy extraction
   causes retry/backoff; the independent 4B supervisor is unchanged.
2. `image_service_pipeline.py` wraps `_generate_result` for pipeline telemetry;
   it does not move the asynchronous job's runtime restoration into the background.
3. `image_service.py::_run_image_job` enters
   `runtime_coordinator.py::image_runtime` under the cross-service runtime lease.
   The coordinator waits for video, releases idle speech/MuseTalk as required,
   stops chat and checks the existing memory admission limits.
4. SDXL/Juggernaut runs exclusively. The provider finishes encoding the artifact;
   the service shuts down the SDXL worker before restoring chat. Failure to unload
   suppresses chat restoration.
5. The **existing** SDXL early publication sets `status=saving`,
   `phase=restoring_chat`, and `result` after SDXL shutdown. The Agent mirrors this
   nonterminal state, `_image_job_tool_result` exposes the artifact, and
   `rendering.js` displays it with restricted controls. Polling continues. This
   already removes chat startup from the earliest image display path; implementing
   a second background restoration path would add risk without that benefit.
6. On context exit, `image_runtime` checks memory again, optionally skips unsafe
   restoration, otherwise synchronously calls `_default_chat_command('start')`.
   It holds the lease throughout. `_run_image_job` marks completion only afterward;
   cancellation or exceptions clear results and generated partial artifacts.
7. The durable Agent queue mirrors native terminal status and only then advances.
   Agent restart resumes polling an existing native ID; loss of a native job after
   image-service restart is treated as failure, rather than redispatching it.

`handoff_timings_ms.chat_restore` measures the entire Bash `scripts/mlx start`
subprocess, not merely `launchctl bootstrap`. `start` calls `wait_for_api`, which
requires successful HTTP `/v1/models` before returning success. Startup failure
propagates through the existing error path. Missing timings remain absent/null.

Source inspection of the installed runtime confirms that `mlx_vlm --model`
preloads the configured language model during FastAPI lifespan before serving;
`mlx_lm` loads its default model on the generation worker startup path. The
management readiness endpoint itself lists models: its HTTP success is **API
readiness**, not a timed test of inference, first-token latency, or weight identity.
No inference warmup is added. Thus the supplied 6,872.18 ms includes process
bootstrap, Python/runtime initialization, model preload and readiness detection,
but cannot attribute time separately to those phases. It is not evidence that
model loading alone took 6,872.18 ms.

Other startup work includes backend detection, configuration/profile validation,
optional hybrid source validation and the model memory guard. No duplicate
initialization was established as dispensable. The two-second sleeps in `restart`
and `reset` are **not** on this stop/start path. Memory-settle retries occur before
image admission and are not part of chat restore.

## Isolated change and measured effect

`wait_for_api` previously slept one second after each failed API probe. It now
sleeps 200 ms, preserving the same endpoint, HTTP timeout, synchronous startup,
error propagation and lease boundaries. The 90-second start budget now counts
elapsed Bash `SECONDS`, including HTTP probe time, instead of counting sleeps.
Bash has integer-second clock granularity; a probe already in progress can finish
after the deadline (curl still has a two-second maximum). No process is killed by
this polling deadline.

The local fixture starts its readiness timer at the first HTTP request and returns
503 until a controlled delay passes, then 200. It executes the real baseline and
patched Bash functions and curl against an ephemeral loopback HTTP server.
Delays: 150, 350, 550, 750, 950 ms, twice each; ten samples per version.
The fixture uses no private data, configurations, models or LaunchAgents.

| Measurement | Baseline | Patched | Reduction |
|---|---:|---:|---:|
| Mean readiness-detection lag | 471.98 ms | 116.23 ms | 355.75 ms |
| Median readiness-detection lag | 467.41 ms | 118.98 ms | 348.43 ms |
| Supplied production chat restore | 6,872.18 ms | **unmeasured** | **unconfirmed** |
| Supplied production total image job | 46,894.60 ms | **unmeasured** | **unconfirmed** |

Raw samples: [benchmark JSON](benchmarks/chat-restore-readiness-2026-11-06.json).
This measures detection overhead, not faster model loading. Poll phase and OS
scheduling matter: the 950-ms fixture was about 83–89 ms slower with the patch,
while the mean improved. Individual jobs are not guaranteed to improve.

Failed probes remain sequential. The sleep-limited rate rises from approximately
one to five probes/second during startup only (slower if HTTP is slow). These are
short-lived curl processes, and the first successful models endpoint may scan the
local model cache. There is no extra resident model or parallel model start.
CPU/process overhead on production hardware and actual RAM/swap changes remain
unmeasured; the fixture cannot establish their absence. No co-residency policy,
memory reserve, hard limit, active-inference handling or supervisor code changes.

## Co-residency analysis only

With the existing defaults on 48 GB, the 90% ceiling is 43.2 GB and the chat and
image load reserves are 18 GB each. An illustrative 12-GB used snapshot plus both
reserves projects to 48 GB, exceeding that ceiling by 4.8 GB. The two-reserve
projection would require used memory at or below 7.2 GB even before allowing for
other uncertainty. Reserves are admission estimates, not measured joint peaks;
neither low idle memory nor successful individual loads prove safe overlap.
SDXL's explicit exclusive release remains mandatory. There is no automatic
co-residency enablement or new opt-in in this patch.

## Validation and local acceptance

New deterministic tests execute the production Bash function with controlled
readiness and time: immediate/delayed success, failure, zero budget, and slow
HTTP probes consuming the deadline. Additional threaded coordinator tests hold
the **real** runtime lease through restore success, cancellation during restore
and restore failure, rejecting a concurrent video lease until restoration exits.
All tests use fixtures and temporary state; no image model is tested here.

Existing regression suites cover image generation, unload ordering, unsafe-memory
restore skips, queue dispatch/recovery/cancellation, active memory extraction,
supervisor behavior, browser polling/resume and early-restoration presentation.
Validation passed: 4,065 existing Python tests (472 subtests), all 408 JavaScript
tests, nine new readiness/lease tests, and two Chromium image-preview/download
cases (desktop/mobile). A separate 38-test run covered the nine new tests plus
dedicated-memory and supervisor regressions. Initial sandboxed runs could not
bind fixture HTTP sockets; reruns with loopback permission passed. There were two
existing dependency deprecation warnings in the full Python suite.

Safe CPU-only acceptance from the repository root:

```sh
bash -n scripts/mlx
test-venv/bin/python -m pytest -q tests/test_chat_restore_readiness.py tests/test_runtime_coordinator.py tests/test_image_runtime.py tests/test_runtime_lock_order.py tests/test_media_queue.py tests/test_dedicated_memory_model.py tests/test_memory_model_supervisor.py
node --test tests/test_image_edit.mjs tests/test_image_job_resume.mjs tests/test_media_cancel_chat_fallback.mjs tests/test_performance_observatory_ui.mjs
test-venv/bin/python scripts/benchmark-chat-readiness.py --baseline-ref 3a2b3e5c
test-venv/bin/python -m pytest --e2e -q tests/e2e/test_acceptance.py -k image_job_preview_download
```

The HTTP fixture and browser tests require permission to bind loopback ports.
For a separate, user-initiated production acceptance, compare equivalent
Juggernaut jobs in Observatory using the same model, seed, resolution, steps and
CFG, record RAM and swap before/peak/after, confirm image visibility during
`restoring_chat` and chat availability after completion. Do not infer a missing
metric as zero. Record every actual image attempt in
`docs/image-model-test-matrix.md`; no real image attempt was made for this patch.

Rollback is a normal `git revert` of the implementation commit. It requires no
data migration or configuration reset. Nothing is deployed automatically.
