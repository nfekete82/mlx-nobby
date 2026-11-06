# Horizontal image results

All image-result cards use the same 900 px maximum width and mobile gutters
as ordinary chat. At 660 px of card content, the preview occupies a fixed
220 px column next to flexible image metadata and controls; below that
threshold, the card stacks into one column. The inline thumbnail uses
`contain` and is capped at 190 px high, so even a tall portrait never expands
a chat message to near-viewport height. Click / keyboard preview opens the
original image; no source-image resizing or change to downloads is performed.
Model/provider, resolution, quality, steps and seed remain visible; prompts
wrap inside the Info disclosure. Each card owns its layout independently.

## Chromium acceptance, 2026-11-06

`tests/e2e/test_image_card_layout.py` runs the production card renderer,
stylesheet, shared preview dialog and privacy CSS in offline Chromium.
Synthetic PNGs and action callbacks replace image services; no model loads,
production chat records or inference endpoints are involved.

| Scenario | Required browser observation |
| --- | --- |
| 1440 px viewport | Card matches normal 900 px chat width, preview ≤195 px high and card ≤340 px high; details to the right |
| 1440 px viewport, 600 px chat container (sidebar constraint) | Single column based on container size |
| 390 px viewport | Single column, no horizontal overflow |
| Portrait, landscape, square; three simultaneous cards | Contained compact preview, independent Info disclosures, long unbroken prompt wraps |
| Keyboard Enter / Escape | Shared large preview opens, closes, restores focus |
| Download | Original synthetic PNG decodes as 1248 × 1664 |
| Region, comparison, regenerate, enhance | All four callbacks receive clicks through the actual layout |
| Privacy; light theme tokens | Blur applies to image; card background follows light tokens |
| `saving/restoring_chat` | Early preview and download visible; heavy-action buttons absent |

The existing JavaScript image-edit, image-preview, media-privacy, regeneration
and served-variant suites cover their complete controllers separately. The
new browser callbacks validate layout hit targets; they do not claim GPU edit
or enhancement execution.

Run with the existing CPU test environment (no new dependency required):

```sh
MLX_IMAGE_CARD_EVIDENCE=artifacts/image-card-ultra-plus \
  python -m pytest -q --e2e tests/e2e/test_image_card_layout.py
node tests/test_image_edit.mjs
node tests/test_image_preview.mjs
node tests/test_media_privacy_ui.mjs
node tests/test_image_variant_served.mjs
```

The optional evidence directory receives desktop, mobile and constrained-width
screenshots. These synthetic local screenshots are excluded from Git under the
repository's binary-artifact privacy policy. No production media is captured.
The first browser invocation failed at Chromium's macOS sandbox handshake;
running this isolated suite with macOS process permission resolved it. An
initial blur assertion read during its CSS transition; it now waits for the
actual final computed filter. PR #435 baseline acceptance: all four original cases passed. The compact-width follow-up changes layout expectations; its revised Chromium suite must be rerun before merge.
