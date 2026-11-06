# Exclusive AI model handoffs

Applies to coordinated **chat**, **image** and **video** heavyweight jobs.

The goal is explicit: when MLX Nobby begins loading a large inference model,
existing *idle* heavy model weights in the other known runtimes must be
released first, even if memory estimates initially look comfortable. We
prefer a cold start over overlapping Apple unified memory allocations.
The existing per-job exclusive lease prevents concurrent coordinated jobs.

The orchestrator is `runtime_coordinator.py`, under its existing
cross-process lease. Explicit `exclusive_models=True` is enabled at all
production image and video entrypoints, and on Agent chat runtime calls.
This does **not** stop Docker, web UI, Agent control plane, filesystem services
or the embedding endpoint.

- **Chat:** unload idle image, speech and MuseTalk model weights (if available).
- **Image:** wait until the video job is idle, unload idle speech/MuseTalk
  weights, then stop the loaded chat model before allocating SDXL/Qwen/Flux.
- **Video:** unload idle image, speech and MuseTalk model weights, and stop
  loaded chat model before allocating LTX weights.
- **After a media job:** chat is restarted *only if it was previously running*
  and the pre-existing post-run memory guards report enough headroom. No
  eager restart of unloaded image or speech models.
- **Preflight:** strict 90%-used admission, model reserves, memory probes,
  active 20%-free guard, 0.5-GB swap growth threshold, CPU offload, and
  backend-specific model cache caps are unchanged.
- **Active tasks:** the runtime lease waits for coordinated jobs. Individual
  service endpoints additionally wait until their own `health` is idle
  before unloading and verify the known model-loaded flags cleared.
- **Optional older services:** an unavailable model service is skipped, and
  older MuseTalk builds without a residency/unload API cannot prove model
  unloading; this is surfaced as a capability limitation, not a claim of
  absolute system-wide exclusivity. macOS also has other non-Nobby processes.

This policy is explicitly opted into by production callsites so
legacy `image_runtime`/`video_runtime` APIs retain their previous behavior
for older internal callers and testing.

## Checks

```bash
./test-venv/bin/python -m pytest -q \
  tests/test_exclusive_model_handoff.py \
  tests/test_runtime_coordinator.py \
  tests/test_sdxl_memory_safety.py \
  tests/test_region_chat_handoff.py
```

After green CI, perform a *real* Apple-Silicon test with one chat response,
one Juggernaut image, one masked 512px Qwen edit and one short LTX video.
Observe processes/heap, swap, job outcomes and chat restoration. A test-only
mock does not establish actual RAM reclamation. Do not tag a release before
final-main local acceptance as defined in `docs/RELEASING.md`.

## Consistent exclusive media preemption (November 2026)

The previous exclusive handoff covered the 27B chat, image/video,
speech and MuseTalk runtimes, but the separately managed 4B memory model
used a pressure-dependent rule for video, edit and upscale. Direct image
endpoints bypassed the Agent queue preemption path altogether.

All native image/video exclusive runtime scopes now request and verify a
4B supervisor handoff *before* loading new weights. The durable Agent queue
also requests exclusive 4B preemption for **every** image and video operation,
not only text-to-image. In-progress 4B extraction finishes under its shared
inference lock; an unready supervisor causes a bounded wait and a safe
defer/error. Original memory jobs are not discarded.

Manually launched or otherwise unmanaged dedicated 4B processes are **never
killed**. If the configured dedicated memory port is still live but not
owned by the supervisor, exclusive media admission fails with an explicit,
actionable error instead of silently sharing RAM. There is no blanket
process kill, system cache purge or force-stop of unrelated applications.

The 4B supervisor checks the cross-process native runtime lease as well as
the Agent's persistent media queue. This prevents a direct image or video
request from allowing 4B to restart after the short dispatch marker expires.

The direct image `/generate`, `/edit` and `/upscale` paths use the same
exclusive runtime mode as queued image jobs. Inside the image-service lock,
idle SDXL and unrelated registered MLX-Serve image models are released before
the selected provider is loaded. Unknown resident MLX-Serve IDs are never
guessed and unloaded; instead the handoff fails closed. SDXL img2img workers
are torn down before 27B restoration, not just SDXL text-to-image workers.
A batch keeps its existing shared lease and releases the warm SDXL worker
before the outer chat restoration.

Nothing changes `ACTIVE_MIN_FREE_PERCENT`,
`ACTIVE_MAX_SWAP_GROWTH_GB`, model admission reserves or the hard 90% used
ceiling. These are safety tripwires, not performance controls. A successful
synthetic test cannot prove that Apple MPS, MLX or macOS has truly reclaimed
memory: test **real Juggernaut XL Ultra+ and LTX** separately under an
uncontended local workload, observing pre-admission, peak free percentage,
swap delta, loaded runtime states and post-job chat restoration.

Targeted tests (offline, fictional state, no model downloads):

```bash
python3 -m pytest -q tests/test_memory_model_supervisor.py \
  tests/test_media_queue.py tests/test_exclusive_model_handoff.py \
  tests/test_runtime_coordinator.py tests/test_sdxl_memory_safety.py
```

For a read-only local memory snapshot:

```bash
python3 - <<'PY'
import runtime_coordinator as rc
print(rc.memory_budget_snapshot())
print(rc.lease_state_snapshot())
PY
```

A baseline of existing swap is not proof of current memory pressure. The
measured **increase during an individual job** and the availability of
reclaimable memory matter. Mac process RSS alone excludes some GPU/Metal
allocations and must not be treated as total unified-memory usage.
