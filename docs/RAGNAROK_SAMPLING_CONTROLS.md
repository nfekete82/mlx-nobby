# Juggernaut image generation: visible Steps and CFG

The image creation quality dialog always had Fast / Standard / Quality
selectors, but did not expose exact sampling steps and CFG. Existing explicit
image options could override presets without being visible.

On the creator-aligned Ragnarok branch, selecting the actual
**Juggernaut XL Ragnarok** image model (not `Auto`) additionally reveals
two numeric inputs and a live effective-settings summary:

- Fast: 20 steps, CFG 4.0
- Standard: 35 steps, CFG 4.0
- Quality: 40 steps, CFG 4.0
- Each field can be edited for a single generation (Steps 1–50, CFG 0–10).
- Clicking a different quality tier resets custom numbers to that tier.
- The currently visible sampling values override stale `image_options`
  steps and guidance in the outgoing chat-action request.
- Changing to a different model hides the fields. Image editing,
  reference generation and video controls remain separate.
- `Ultra` is hidden when Ragnarok is explicitly selected because its
  1536px native request exceeds the current SDXL service hard cap 1216.
- Custom values are not written to persistent model defaults; cancelling
  the dialog creates no job. The backend preserves the validated values.
- Auto routing may select a different image model. To control Ragnarok
  sampling precisely, choose it explicitly in the image model picker.
- All RAM admission, CPU offloading and active watchdog protections remain
  unchanged. These UI fields do not bypass them.

Validation:
```bash
node --test tests/test_ragnarok_sampling_controls.mjs
node tests/test_image_option_contracts.mjs
node tests/test_media_quality.mjs
./test-venv/bin/python -m pytest -q tests/test_image_option_validation.py
```

Install on the Mac after PR CI and while idle:
```bash
cd ~/mlx-web
git pull --ff-only origin fix/juggernaut-unified-memory-safety
docker compose up -d --build --no-deps mlx-web
```

This is only a UI/frontend change to existing supported image parameter
fields; no image-service restart or model re-download is necessary.
