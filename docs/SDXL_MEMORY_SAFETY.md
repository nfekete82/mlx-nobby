# SDXL unified-memory safety (Apple Silicon)

This safety pass applies to **both** Juggernaut XL and Lustify Endgame, and
reuses the standard global load-admission coordinator.

## Defaults

- **No simultaneous warm chat + SDXL image generation**: the image runtime
  releases an active chat service before an SDXL job, even when free RAM still
  appears comfortable. Chat is restored after the image worker has unloaded,
  only if memory headroom is safe.
- **MPS allocator hard ceiling**: the SDXL child inherits
  `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.55` and
  `PYTORCH_MPS_LOW_WATERMARK_RATIO=0.45`, overriding unsafe inherited values.
  Higher requested limits are clamped. This limits MPS allocations, *not*
  all CPU/Metal allocations on the system.
- **Active system watchdog**: samples macOS `memory_pressure` and swap during
  both SDXL and other native image worker jobs. Stops the subprocess if
  estimated system free percentage falls to **20%**, swap grows by **0.5 GB**
  during that job, or the worker exceeds the existing 24 GiB RSS cap.
  A failed/unknown pressure measurement fails closed.
- **Preload disabled**: `POST /prewarm` returns a safety reason instead of
  loading SDXL by default. If explicitly reenabled via
  `MLX_IMAGE_SDXL_PREWARM=1`, prewarm still uses the same active watchdog.
- The SDXL idle timeout is reduced from 600 to 60 seconds for callers outside
  the normal job flow. Completed SDXL image jobs unload immediately.
- Existing model admission still rejects jobs projected above the 90% hard
  ceiling. The active SDXL/image threshold triggers earlier.

## Configuration (only stricter settings are allowed)

| Variable | Default | Range |
| --- | --- | --- |
| `MLX_RUNTIME_ACTIVE_MIN_FREE_PERCENT` | 20 | 20–40 |
| `MLX_RUNTIME_ACTIVE_MAX_SWAP_GROWTH_GB` | 0.5 | 0.1–1.0 |
| `MLX_IMAGE_SDXL_MPS_HIGH_RATIO` | 0.55 | 0.30–0.55 |
| `MLX_IMAGE_SDXL_PREWARM` | 0 | 0/1 (enables explicit preload) |

## Verification

```bash
cd ~/mlx-web
./test-venv/bin/python -m pytest -q \
  tests/test_sdxl_memory_safety.py \
  tests/test_lustify_sdxl.py \
  tests/test_runtime_coordinator.py
```

After merging/updating the local branch, restart the images launchd service:

```bash
./scripts/mlx services
launchctl kickstart -k "gui/$(id -u)/de.nobby.mlx-images"
```

**Limitations:** No userspace watchdog can absolutely guarantee an OS never
freezes from sudden external allocations or kernel-level memory pressure.
This is a best-effort fail-closed safeguard with a separate MPS allocator
ceiling. Benchmark scripts spawning their own SDXL worker are not covered by
the image-service coordinator. For a machine with 48 GB of unified memory,
do the first validation at 512×512, with no other heavy models running.

## Memory-optimized SDXL execution (post-512x512 real-world OOM)

A Mac with 48 GiB unified RAM exhausted the **existing** safe MPS cap during
Lustify loading: PyTorch reported 10.10 GiB MPS allocations, 11.62 GiB
other allocations and 20.59 GiB allowed total. This is a **safe workload
failure** rather than a reason to raise or disable the allocator cap.

Both SDXL checkpoints now run with `enable_model_cpu_offload(device="mps")`
rather than eager `.to("mps")` weight transfer. Offloading serializes
the UNet, text encoders and VAE across CPU/MPS phases. This trades some speed
for fewer simultaneous MPS-resident components while retaining original
checkpoint weights, quality and generation settings.

The worker additionally enables VAE tiling/slicing. Attention slicing is
**not** enabled alongside offload, as that combination has generated black
SDXL images in certain Diffusers/PyTorch MPS versions. Missing Accelerate
support is a hard, actionable error: never fall back to loading all components
to MPS or disabling the watermark.

The image service has pinned `diffusers==0.40.0` and
`accelerate==1.15.0` in `requirements/images.txt`.

After updating:
```bash
cd ~/mlx-web
./image-venv/bin/python -c 'import diffusers, accelerate; print(diffusers.__version__, accelerate.__version__)'
./test-venv/bin/python -m pytest -q tests/test_sdxl_memory_safety.py tests/test_image_runtime.py -k 'sdxl or memory'
launchctl kickstart -k "gui/$(id -u)/de.nobby.mlx-images"
```
First test with a single 512x512 image; compare memory and reject solid
black output. CPU component offloading is experimental on some MPS
combinations: a physical Mac smoke run is required before merging.
