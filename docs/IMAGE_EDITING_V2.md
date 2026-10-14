# MLX Nobby — Image Editing 2.0 (Precision & Comparison)

## Scope

This is a bounded local-first first iteration of targeted image editing,
not a claim of human-level visual understanding or perfect object segmentation.

### 1. Conservative auto-mask for Qwen Image 2.1 Edit

The existing MFLUX `--auto-mask` backend already knows how to segment
a textual object. Nobby can now extract a **single, unambiguous target**
from simple German/English commands, for example:

- `Mach den Pullover blau, aber verändere sonst nichts.`
  → request MFLUX to mask **sweater**
- `Change the jacket to black, keep everything else.`
  → mask **jacket**
- `Verbessere die Beleuchtung.`
  → **no** automatic mask
- `Mach die Jacke und die Hose blau.`
  → **no** automatic mask (ambiguous)

This does **not** itself detect pixels. MFLUX is responsible for
segmentation; real-world results require visual review. Inference is
restricted to MFLUX Qwen 2.1 Edit, a single source image, and actual edits,
not reference generation. Explicit `mask_path` or `auto_mask` always
takes precedence. `precision_edit: false` on an API edit request
restores the previous unmasked behavior.

No external segmentation service, cloud API, extra model download, new
resident worker or modification of the established Step Cache defaults.

### 2. Before/after comparison

Successful image edits publish `source_image_id` when the original is
available through the existing local images API.

- When the source is an earlier Nobby-generated image, its existing image
  ID is reused.
- For uploads/attachments, a 1024px-or-smaller **local private, EXIF-free**
  preview is saved under `~/.config/mlx-web/images/` with file permissions
  0600. This is a separate local copy; the user's original is never
  overwritten. These previews can remain on disk until explicitly cleaned.
- Each eligible image-edit card gets **Before / after**; the modal has a
  keyboard-friendly native range slider and a close button. Source images
  are fetched only from `/api/mlx/images/{validated-id}`, never via
  user-supplied paths or remote URLs.

### 3. Advisory change estimate (not a semantic quality score)

After the image is generated Nobby compares sampled RGB pixels
at at most 256px. The artifact reports `quality_check.changed_fraction`;
values below 0.1% or above 99.5% set status `review`, otherwise
`unverified`. An edit might legitimately change the entire scene or only
a few pixels. The number is therefore **descriptive only**: it does not
assert identity preservation, instruction-following, correctness, or
quality improvement.

The summary is in the image card's Info disclosure. It does not
automatically reject, rewrite, regenerate or replace any user media.
No private prompts, original paths or image data are sent to telemetry.

## Guardrails and deployment

- Existing 90% global memory gate, 20 GiB reserve policy, 24 GiB image
  subprocess RSS watchdog, source-path validation and cancellation remain.
- Step Cache and KV Cache options are untouched.
- Safe default: ambiguous instructions use the existing global image edit.
- No additional network access beyond same-origin existing images API.

On a separate worktree:

```bash
python -m pytest -q tests/test_image_edit_precision.py
node --test tests/test_image_compare.mjs tests/test_image_preview.mjs
python3 scripts/i18n-audit.py
```

Deploy only after CI passes, then update the working repository and
restart the image service **while idle**, plus the agent (image artifact
bridge) and the chat frontend process if required by your deployment.
Perform a real reference-image edit and check MFLUX auto-mask,
the slider and the advisory manually.

## Next iterations (not part of this PR)

- Interactive brush/region selection and *edit this selection* resubmission.
- Vision-grounded object localization for uncommon objects.
- Region-aware preservation score based on a reliable segmentation mask.
- Optional image-model evaluator against the user's actual edit instruction.

These cannot be safely claimed from a regex target finder or a pixel
difference count alone.
