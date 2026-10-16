# Juggernaut XL Ragnarok – author-aligned local settings

This is the Ragnarok checkpoint `juggernaut-xl`, *not* the older Juggernaut
v9 or the Lightning/DMD2 variant.

## Primary source

KandooAI's original Ragnarok model description and responses:
https://civitai.com/models/133005?modelVersionId=1759168
(archival text at https://civarchive.com/models/133005?modelVersionId=1759168)

Recommended by author: native portrait 832x1216, DPM++ 2M SDE sampler,
30–40 steps, CFG 3–6 (lower CFG often increases realism), start without
negative prompts, baked-in VAE. Creator also advises prompts around <=75
CLIP tokens rather than very long weighted prompt strings.

RunDiffusion Ragnarok guide:
https://www.rundiffusion.com/juggernaut-xiii-ragnarok

Karras sigma choice is supported by a public community Ragnarok ComfyUI
workflow, not explicitly required by the model author's short sampler line:
https://github.com/mobcat40/ComfyUI-PromptChain/blob/master/data/models/juggernaut_xl_ragnarok.json

## MLX-Nobby choices

| Setting | Default | Source/choice |
| --- | --- | --- |
| Runtime sampler | `dpmpp-2m-sde-karras` | Ragnarok SDE + community Karras; Diffusers `sde-dpmsolver++` |
| Steps | 35 standard / 40 quality | Chosen within recommended 30–40 range |
| CFG | 4.0 | Chosen within recommended 3–6 range for photorealism |
| Native portrait | 832x1216 | Explicit **Ragnarok-Porträt** image-format picker option |
| Negative prompt | None by default | Creator: add only if needed |
| VAE | Included checkpoint VAE | No external VAE |
| Fast | 20 steps at 768 long edge | Intentional fast tradeoff, *not* maximal quality |

The portrait format is **opt-in**, shown when Juggernaut is explicitly
selected. Other 9:16, 3:4, landscape and square formats are retained
with their exact aspect ratios. Native width/height are normalized by
the selected quality tier: Standard and Quality have a 1216 long edge.

Registry migration v8 -> v9 changes only previously shipped Ragnarok values
30 steps -> 35, guidance 5.0 -> 4.0, retaining enabled/default-model flags
and other user-configured values. Any explicit `steps`, `guidance`,
`negative_prompt` or `seed` on a generation request always wins. This
migration has no external model downloads and does not delete existing images.

## Deliberately not included

- An extra upscaler/HiRes latent second pass is **not** available in the
  existing guarded SDXL pipeline. The author's separate recommendation
  (4xNMKD-Siax_200k, 15 steps, 0.3 denoise, 1.5x) would require a new,
  safely tested inference path. Native rendering is used instead.
- No guarantees of perfect anatomy/face realism: the creator notes
  that distant faces remain an SDXL limitation.
- The unified-memory watchdog, MPS high-watermark cap, CPU offloading,
  chat handoff, VAE compatibility and service restarts remain untouched.

For local rollout after CI and while the image service is idle:

```bash
cd ~/mlx-web
git pull --ff-only origin fix/juggernaut-unified-memory-safety
./test-venv/bin/python -m pytest -q \
  tests/test_ragnarok_creator_presets.py \
  tests/test_juggernaut_quality_policy.py \
  tests/test_image_runtime.py
launchctl kickstart -k "gui/$(id -u)/de.nobby.mlx-images"
curl -fsS http://127.0.0.1:8030/health
```

A real native 832x1216 image generation on the user's Apple Silicon Mac
is still required for the subjective photo-quality assessment.
