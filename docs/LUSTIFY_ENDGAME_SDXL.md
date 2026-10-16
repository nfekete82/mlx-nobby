# Lustify Endgame (SDXL) in MLX Nobby

Lustify Endgame is a **second, independent local SDXL checkpoint** next to
Juggernaut XL Ragnarok. Both use the existing persistent Diffusers/PyTorch-MPS
worker (`sdxl_worker.py`), scheduler presets, image service and browser model
picker; no new provider or network inference is added.

| Model | Stable registry ID | Local directory | Default steps | Default CFG |
| --- | --- | --- | ---: | ---: |
| Juggernaut XL Ragnarok | `juggernaut-xl` | `~/Models/JuggernautXL` | 30 | 5.0 |
| Lustify Endgame **standard** | `lustify-endgame-sdxl` | `~/Models/LustifyEndgame` | 30 | 3.5 |

The existing Juggernaut ID is retained to avoid breaking older sessions,
presets, saved images and existing registry selections.

## Install local weights

Use the **ENDGAME** SDXL checkpoint, **not ENDGAME DMD2**, Lightning, Pony,
Illustrious or the separate Krea 2 generation of Lustify. DMD2 needs a
different low-step/low-CFG sampling contract.

Download the ~6.94 GB standard Endgame checkpoint from the creator's
[CivitAI model page](https://civitai.com/models/573152) (version 1094291).
A known HF copy is available under
[MishGUN1/LUSTIFY](https://huggingface.co/MishGUN1/LUSTIFY/blob/main/lustifySDXLNSFW_endgame.safetensors).

Example for a machine that already has Ragnarok's offline SDXL config:

```bash
cd ~/mlx-web
mkdir -p ~/Models/LustifyEndgame

# Reuse existing local SDXL 1.0 Diffusers config, not the checkpoint.
cp -R ~/Models/JuggernautXL/config ~/Models/LustifyEndgame/

# Alternatively download the standard Endgame from CivitAI and place it here.
curl -fL --retry 3 \
  -o ~/Models/LustifyEndgame/lustifySDXLNSFW_endgame.safetensors \
  "https://huggingface.co/MishGUN1/LUSTIFY/resolve/main/lustifySDXLNSFW_endgame.safetensors"

shasum -a 256 ~/Models/LustifyEndgame/lustifySDXLNSFW_endgame.safetensors
```

Expected SHA256 for the **HF copy** shown above:

`8c7b3ca29623c55c876fea72723ab5d464d8606c60056caae40cfbc173beb1f1`

Before enabling, verify exactly **one** .safetensors checkpoint in
`~/Models/LustifyEndgame`, with `config/model_index.json` present.
Local model validation deliberately fails if checkpoint selection is
ambiguous. No automatic download runs on startup or while loading the picker.

In **Einstellungen → Bildmodelle**, enable
**Lustify Endgame (SDXL)** once its local files are present. Then select it
in the image-generation dialog. Selection is per request: automatic routing
and the global default remain unchanged. If wanted, explicitly activate it
as the global default in Image Settings.

The persistent registry (`~/.config/mlx-web/image-models.json`) gains a
disabled Lustify entry while preserving Ragnarok's enabled state, custom
steps/CFG and default role.

## Defaults and runtime

- Standard/quality: 30 steps, CFG 3.5; quality long edge 1216.
- Default production SDXL scheduler: DPM++ 2M Karras.
- A/B default scheduler: DPM++ 2M SDE Karras for both models.
- Manual seeds and negative prompts work with both normal SDXL variants.
- Only one SDXL pipeline is resident; switching the checkpoint unloads
  the previous pipeline before loading the next.
- Existing memory safeguards, job cancellation and offline execution apply.
- SDXL remains **text-to-image**; no image-edit or inpainting added.

## Comparable A/B benchmark

```bash
# Check planned settings and filenames without GPU:
python scripts/benchmark-sdxl-models.py --dry-run

# Render two runs per model (image service running at :8030):
python scripts/benchmark-sdxl-models.py \
  --seed 42 --repeats 2 --steps 30 --cfg 3.5 \
  --width 832 --height 1216 \
  --scheduler dpmpp-2m-sde-karras \
  --prompt "Photorealistic portrait of an adult, natural light, detailed skin"
```

The script unloads the image service worker first, uses **identical prompt,
negative prompt, seed, steps, CFG, canvas and scheduler**, and renders
sequentially to reduce unified-memory pressure. PNGs and a JSON timing/hash
manifest are saved in `~/.config/mlx-web/benchmarks/sdxl-ab/`.
Warmup is excluded from generation timing. Hashes help investigate
reproducibility on the same machine/runtime; different checkpoints should
not produce identical images, and GPU results can vary between versions.

Use `--skip-service-unload` only if a separate concurrent worker is safe.

## Test commands

```bash
python -m pytest -q tests/test_lustify_sdxl.py \
  tests/test_juggernaut_quality_policy.py
node --check frontend/assets/chat/generation.js
node --check frontend/assets/chat/image-settings.js
```

Real generation and A/B assessment require the checkpoint weights,
Apple Silicon MPS and adequate memory.
