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
