# Juggernaut XL Ragnarok — Image-to-Image (img2img)

## Use

1. In an MLX Nobby chat, attach one image (PNG, JPEG or WebP).
2. Set **Bild verwenden für → Bearbeiten (Edit)**.
3. In **Bearbeitungsmodell**, choose **Juggernaut XL Ragnarok**.
4. Set **Veränderungsstärke / Strength** (0.15–0.85, default 0.45).
5. Optionally open **Weitere Optionen** to set Steps (1–50), CFG (0–10) or a reproducible Seed. If blank, Nobby uses the selected quality/model defaults and a random seed.
6. Enter a scene/style instruction and start the image job, choosing normal quality.

The edit uses an SDXL image-to-image denoising pipeline. This is **not**
precision editing: facial identity and individual elements may change. Qwen
Image Edit remains recommended for region masks, object edits and multi-image
composition. Original images are not overwritten. The image and output stay
local.

## Technical contract

- Built-in stable model ID: `juggernaut-xl`, provider `sdxl`.
- Adds advertised `image_edit`, `img2img`, `edit_strength` capabilities, but
  continues to support text-to-image independently.
- Edit jobs are dispatched through the existing Agent, image queue and memory
  coordinator. A one-image request selects the SDXL worker; ordinary text-to-
  image requests never receive a source image.
- The worker **shares the existing SDXL components and CPU offload hooks**
  between text-to-image and img2img, rather than loading the checkpoint twice.
  It continues using the same MPS RAM/swap guard and idle shutdown.
- The unmodified image remains the source of truth. A temporary, permission-
  restricted RGB copy respects EXIF orientation, aligns dimensions to multiples
  of eight and caps the longest edge at 1024 pixels to bound memory demand.
  Extreme panoramas over 4:1 are rejected instead of distorted; temporary
  sources are deleted even when a job fails or is cancelled.
- Denoising strength defaults to 0.45. Normal Pydantic bounds accept
  `0 < strength <= 1`; the UI offers the safer 0.15–0.85 range.
- Explicit negative prompts and ordinary SDXL steps/CFG/seed are supported.
  Qwen-specific masks, KV cache and multi-reference edit controls are rejected
  for Juggernaut; no hidden fallback to Qwen or remote download is introduced.
- Result metadata stores model, provider, seed, steps, guidance, strength and
  the original source path for regeneration/provenance.
- SDXL's denoising progress only covers `floor(steps * strength)` effective
  inference steps; the generic progress validator accounts for that reduction.

## Validation

Offline CPU tests:

```bash
python3 -m pytest -q tests/test_juggernaut_img2img.py tests/test_sdxl_memory_safety.py
node --test tests/test_juggernaut_img2img_ui.mjs tests/test_image_edit_single_model_picker.mjs
```

Release validation (only on the user's Apple Silicon host when image services
are idle): `./scripts/mlx test-release` and a **real** img2img job with
`juggernaut-xl` selected, followed by a text-to-image regression. Confirm
the source file remains identical, output format/size are valid, model output
uses the active memory guard, and no new model downloads occur. A simulated
worker test or green CI alone does not establish real Mac runtime compatibility.

The target release is v1.20.0, contingent on a separate, metadata-only release
PR and successful final-main Apple Silicon acceptance. No tag or GitHub Release
should be published from this feature branch.
