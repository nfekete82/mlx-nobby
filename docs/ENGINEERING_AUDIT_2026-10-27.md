# Engineering audit and bounded resource fixes — 2026-10-27

Historical first-pass report. The [activation and native follow-up](ENGINEERING_ACTIVATION_2026-10-27.md)
supersedes its pending-activation status and shared-threadpool implementation.

Baseline: `2adfa81`, branch `main`. Existing untracked LTX experiments,
benchmarks and documentation were preserved. Changes remain uncommitted.

## A. Initial state and priorities

The highest-impact confirmed defect was full-file reading in both Agent log
APIs. `collect_log_sources()` and `mlx_log_lines()` decoded and split each whole
log before selecting its last lines. The local `agent.log` was approximately
9.9 GB. Even a small diagnostic request could therefore allocate multiple
gigabytes and compete with model inference for unified memory.

Two web upload handlers also performed blocking work directly on the ASGI event
loop: PDF parsing/extraction plus an Agent indexing request (30-second timeout),
and the speech transcription request (180-second timeout). Concurrent streams,
uploads and status requests could stall while those operations ran.

Both Real-ESRGAN paths used blocking `stdout.readline()` before checking their
840-second deadline again. A silent child, or a partial line without a newline,
could prevent timely cancellation and timeout handling. Their process-output
loops duplicated the same unsafe approach.

The browser's buffered TTS cache limited entries to 40 but had no byte budget.
Long responses could therefore retain substantially more audio than short ones.

These concrete resource and reliability defects took priority over model tuning
and cosmetic restructuring.

## Architecture and inspection scope

Source inspection covered entrypoints, Docker/launchd/startup configuration,
dependency manifests, model-provider locking, embedding dispatch, image/video
process lifecycle, runtime leases and admission, local HTTP/path/upload guards,
frontend polling/render coalescing and speech caches, and relevant tests/docs.
This is a targeted engineering audit, not an exhaustive security certification
or real-model quality evaluation.

Observed loopback TCP listeners:

| Port | Component |
| ---: | --- |
| 8000 | Native chat runtime |
| 8010 | Native Agent/API bridge |
| 8020 | Embedding adapter |
| 8030 | Image service |
| 8040 | Router/vision service |
| 8050 | Speech service |
| 8060 | Video dispatcher |
| 8090 | Docker web frontend/backend, published through OrbStack |
| 11234 | Shared MLX-Serve endpoint |

No listener was observed on 8070. Optional MuseTalk coordination remains in the
code; it should not be inferred to be an active service from that alone.
The browser uses the web backend, which bridges native calls through the Agent.
Embeddings and supported image providers share MLX-Serve; heavyweight media and
chat handoffs use the existing runtime coordinator.

Installed runtime distribution metadata matches the manifest: MLX 0.32.2,
MLX-LM 0.31.3, MLX-VLM 0.6.17, Transformers 5.17.0, arm64. No model was loaded
to obtain these versions. The requested hardware budget is 48 GB; the sandbox's
memory probe returned no physical-capacity value, so this audit does not claim
an independently measured host capacity or GPU memory peak.

Existing cross-process leases, consistent lease-before-model-lock ordering,
fresh admission probes, diagnostic-only memory caching, the 90% admission cap,
18 GB image / 20 GB video load reserves and active memory watchdogs were retained.
Model routing, tokenization, sampling, context handling, quantization, KV/APC
caches and DFlash2 behavior were not changed. The documented experimental
Hybrid activation HOLD still applies.

## B. Implemented changes

| Files | Result |
| --- | --- |
| `agent/log_tail.py`, `agent/app.py` | Shared reverse block reader for both log APIs; at most 1 MiB read per file. Preserves ordinary line order, UTF-8 and each endpoint's existing NUL handling. |
| `backend/app.py` | Keeps asynchronous bounded upload reads; runs PDF parsing, extraction, indexing and transcription forwarding in Starlette's existing bounded threadpool. Response/error contracts remain covered. |
| `image_providers.py`, `image_service.py` | One readiness-based pipe reader replaces both blocking loops. Cancellation and deadline checks continue during silence, partial output and early pipe closure. Progress supports CR/LF, UTF-8 and final unterminated output. Diagnostic fragments are bounded; pipe/process cleanup remains explicit. Quality+ removes its temporary file after stopping its child. |
| `frontend/assets/chat/tts-cache.js`, `frontend/assets/common.js` | Caps retained audio Blob payloads at 32 MiB in addition to 40 entries, evicting oldest entries. Oversized responses still play and are not retained. Refreshes the asset revision. |
| `tests/test_log_tail.py`, `tests/test_upload_concurrency.py`, `tests/test_upscale_process_io.py`, `tests/test_tts_cache.mjs` | Behavioral regressions for bounds, API reuse, live event-loop responsiveness, real subprocess cancellation/cleanup and audio-cache eviction. |
| `tests/test_image_runtime.py`, `tests/test_image_quality_v2.py` | Progress fixtures now expose real pipes. Two stale portrait-routing assertions now match the Qwen preference introduced by `b9acecf3`; existing Juggernaut fallback assertions remain. |
| `scripts/benchmark-log-tail.py` | Reproducible CPU-only comparison using temporary synthetic logs. |

Log-tail safety intentionally takes precedence over returning every requested
line from pathological logs: at the byte ceiling, the incomplete leading line
is omitted if other lines exist; a single oversized line returns a bounded
suffix. Limits apply to input bytes, not total Python allocation. The TTS byte
budget covers retained Blob payloads, not all browser memory or in-flight audio.
Threadpool offloading preserves responsiveness; it does not make PDF processing
faster or forcibly interrupt an already running blocking request.

## C. Measured performance

Local arm64 host, existing `test-venv` Python 3.13, synthetic 64 MiB file,
256-byte lines, identical last 400 lines, five alternating warm-file-cache
trials. Allocation peaks were measured separately with `tracemalloc`.

| Metric | Previous full reader | Bounded reader |
| --- | ---: | ---: |
| Median elapsed | 68.396 ms | 0.221 ms |
| Python allocation peak | 140.209 MiB | 0.404 MiB |

Reproduce with `test-venv/bin/python scripts/benchmark-log-tail.py`.
These numbers describe this synthetic reader workload, not model TTFT, tokens/s,
GPU memory, live API latency or a cold disk. The real 9.9 GB log was not loaded
for benchmarking. No inference speedup or host-wide RAM reduction was measured.

## D. Validation and limitations

338 distinct targeted Python tests passed across the executed groups, with
54 additional subtests; 22 targeted JavaScript tests passed. Coverage includes
the changed paths and runtime budget/coordinator, queue, health caching, local
HTTP protection, embeddings, image routing/quality, natural upscaling and speech
UI regressions. Syntax checks for changed Python/JavaScript, Compose validation
and `git diff --check` passed. No dependencies were added.

Upload concurrency tests hold PDF extraction, PDF indexing or transcription in
a worker and require a real ASGI health response before releasing that worker.
Subprocess tests use short-lived CPU-only Python children, not Real-ESRGAN or
models, and exercise silent/partial/closed pipes, deadlines, cancellation,
progress, bounded output, process reaping and callback cleanup.

The broader image run initially exposed the stale routing assertion. The same
failure reproduced from an isolated archive of the unchanged baseline. Git
history explicitly records the intentional Qwen preference in `b9acecf3`
(`feat(images): route auto image generation to Qwen Image 2.1`). Only the two
outdated expectations were corrected; production model selection is unchanged.
The resulting complete selected image group passed. An existing Starlette
TestClient/httpx deprecation warning remains; no dependency upgrade was attempted.

The full repository/release matrix, Chromium acceptance, Docker image rebuild
and native model/image/video benchmarks were not run. Production services were
not restarted and private runtime logs/content were not copied into diagnostics.
This is not release acceptance or confirmation of live activation.

## E. Relevant next opportunities

1. **Bound log growth operationally.** Readers are now safe, but launchd stdout
   files can still grow. Choose retention and rotation with open-file handling
   in mind; coordinate this with an idle maintenance window. No logs were deleted.
2. **Reduce converter export memory.** `backend/image_converter.py` bounds input
   sizes and serializes encodes, but builds the ZIP in memory. File-backed export
   with disconnect cleanup and a documented output budget warrants its own
   HTTP/large-output acceptance; compressed input limits alone do not bound ZIP
   output or decoded image memory.
3. **Validate native acceptance after activation.** Confirm normal and cancelled
   Real-ESRGAN jobs, PDF indexing, transcription and chat/media handoffs on the
   installed runtimes. GPU latency, quality and long-run memory behavior still
   require an idle hardware session; these CPU tests cannot certify them.

## F. Git and activation

Branch: `main`; no commit, staging, push, release, dependency installation or
production restart was performed. Fifteen files belong to this change, all
listed above plus this report. Pre-existing untracked work remains untouched.

Activation requires an idle maintenance window: restart the Agent and image
service, rebuild/recreate the web container, then reload the browser. Available
local commands (not executed by this audit):

```sh
./scripts/mlx agent restart
launchctl kickstart -k "gui/$(id -u)/de.nobby.mlx-images"
docker compose up -d --build mlx-web
```

Use the repository's existing real-runtime acceptance after activation. Do not
interpret a development-source fix as a fix already applied to running processes.
