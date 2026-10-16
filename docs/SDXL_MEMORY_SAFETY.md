# Juggernaut XL Ragnarok: unified-memory protection

Standalone RAM-safety improvements for **Juggernaut XL Ragnarok** only.
The earlier Lustify Endgame experiment is retired, not a runtime dependency.

- Limit PyTorch's MPS high-watermark allocation to at most 55% of unified
  memory, regardless of inherited environment settings.
- Use CPU component offloading instead of moving the entire SDXL pipeline
  eagerly to MPS. Use optional VAE tiling/slicing on AutoencoderKL where
  supported. No unsafe fallback.
- Watch macOS-wide free-memory percentage, *new* swap growth and process RSS
  while generating. Stop the worker if reported free memory reaches 20%,
  swap rises 0.5 GiB or process RSS exceeds 24 GiB.
- Release a heavy chat model before SDXL generation and release SDXL before
  restoring chat; do not restore chat if SDXL termination fails.
- Disable speculative SDXL prewarm by default and reduce worker idle time.
- Retire saved `lustify-endgame-sdxl` entries from the local model registry.
  The model is not shipped as a built-in; deleted defaults are reset to an
  enabled Ragnarok, or the established legacy fallback. Preserve other
  model settings and all generated images.

## Mac setup

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/fix/juggernaut-unified-memory-safety
./test-venv/bin/python -m pytest -q \
  tests/test_sdxl_memory_safety.py tests/test_lustify_retirement.py \
  tests/test_runtime_coordinator.py
launchctl kickstart -k "gui/$(id -u)/de.nobby.mlx-images"
curl -fsS http://127.0.0.1:8030/health
```

Lustify model weights at `~/Models/LustifyEndgame` are **not** deleted by
the registry migration: disk deletion requires an explicit separate action
on the Mac. Existing images and benchmark outputs are not deleted.

A userspace watchdog cannot absolutely guarantee against third-party or
kernel-level memory spikes. Never set
`PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0`.
