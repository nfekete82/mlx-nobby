# Region editor 1.1 – zoom, brush shortcuts, prompts and inner feather

The working **Bereich bearbeiten** 1.0 and its low-RAM model path from
PR #267 are unchanged. This follow-up touches the visual editor and the
optional, deterministic final composite step.

- **Zoom:** fit, +, −, up to 300%; scroll around the image using its viewport.
  The source and painted mask zoom together; pointer coordinates remain
  natural-image pixels, so the server receives the original PNG-sized mask.
- **Shortcuts:** B (brush), E (eraser), Cmd/Ctrl+Z (undo) when not typing;
  +/−/0 for zoom, Esc to close. Browser text-entry shortcuts still work.
- **Brush size:** remembered on-device in localStorage, with a 32px fallback.
- **Prompt templates:** eye color, skin texture, remove object and recolor
  clothing; all templates are editable before submitting. Qwen still receives
  the selected text, not a hidden instruction.
- **Soft edge:** 0–12px, default **3px**, applied only during composition of
  the 512px-or-smaller AI edit crop. Uses a blurred selection clipped *inside*
  the original painted mask; hence absolutely no pixel outside the user's
  selection can change. 0px reproduces the old crisp-mask behavior.
- **Memory handoff:** low-RAM masked Qwen region jobs now request the
  same exclusive chat-model unload as SDXL. Chat is restored only when the
  existing coordinator judges memory safe. This avoids overlapping a large
  resident chat model with a fresh Qwen Edit process. Ordinary unmasked edits
  keep their original pressure-aware handoff.
- **Safety:** no model install, new image dimensions, changed model cache,
  active swap watchdog (still **0.5 GB delta**), concurrency logic, or
  additional generation passes. The editor still crops to <=512x512 pixels.
  Original image retained. The new `region_feather_px` option is restricted
  to the image-edit request contract and validated by Pydantic (0–12). It
  cannot be used with a generic image edit or reference generation.

Notes: feathering may soften detail *inside* the selection. For extremely
small iris edits, test 0–2px rather than 3px. Mask softness is *not* the
brush's visual red overlay and does not automatically extend a selection.

Testing:
```bash
./test-venv/bin/python -m pytest -q \
  tests/test_region_ux_polish.py tests/test_region_memory.py \
  tests/test_region_chat_handoff.py tests/test_image_option_validation.py
node --test tests/test_region_ux_polish.mjs tests/test_region_mask_editor.mjs
```

Deployment on Mac after reviewing branch and when image service is idle:
```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/feat/region-editor-ux-polish
./scripts/mlx agent restart
launchctl kickstart -k "gui/$(id -u)/de.nobby.mlx-images"
docker compose up -d --build --no-deps mlx-web
```
