# MLX-Nobby – Bereich bearbeiten (MVP 1.0)

**New UI:** Each generated image in the chat and media-library card/preview
has a **Bereich bearbeiten** action. Clicking it opens an overlay with:
a source image, red brush selection, eraser, undo, reset, brush-size slider,
and an optional user instruction up to 2000 characters. No model executes
while the user is painting. The edit only starts when clicking the action.

The browser paints an opaque black-and-white PNG mask at exact natural
source dimensions: **white pixels are edited, black pixels preserved**.
The red highlight is visual-only. The PNG is uploaded through the already
authenticated `/api/mlx/batch/upload` endpoint. A queued `image_edit`
request binds `active_artifact_id` to the original server-managed
`image-<id>` and supplies the managed `mask_path` to the existing
image-edit backend, which validates path, image dimensions and nonempty
mask. The auto-router chooses an enabled compatible Qwen 2.1 Edit model,
and fails explicitly if the installed CLI does not support masking. The
system never silently falls back to whole-image editing.

Existing image job tracking, unified-memory concurrency guard,
image history, cancel handling and the before/after comparator are reused.
The original image is never modified; a distinct edited PNG is saved to
the same local, private media library.

Scope/limitations:
- Generated image artifacts and media library images only (direct user
  upload editing continues through the existing attachment editor).
- **Brush, eraser, undo, clear**; rectangle and lasso deferred.
- Browser preview labels selected pixels; the model may still change
  surroundings. The existing advisory/compare workflow is essential.
- A chat session must be active to enqueue an edit.
- PNG mask and original must share pixel dimensions. Image edges larger
  than 16 megapixels are blocked by the editor.
- No face detection, automatic quality score or external cloud calls.
- No CPU/GPU model settings, VAE, image generator or RAM safety changes.

Smoke tests:

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/feat/region-prompt-image-editor
node --test tests/test_region_mask_editor.mjs
./test-venv/bin/python -m pytest -q tests/test_region_mask_editor.py
docker compose up -d --build --no-deps mlx-web
```

For end-to-end validation: open any generated image, click
**Bereich bearbeiten**, paint a small region, submit a prompt. Check that
the edit creates a separate result, and the result's **Vorher/Nachher**
shows the original. The image edit service must be available and
support the `--mask-image` option.
