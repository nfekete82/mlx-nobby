# Juggernaut XI v11 defaults

MLX Nobby keeps the stable registry ID `juggernaut-xl` and the local
directory `~/Models/JuggernautXL` for backward compatibility, but the
supported checkpoint is now **RunDiffusion Juggernaut XI v11**.

Expected local layout:

- `~/Models/JuggernautXL/Juggernaut-XI-byRunDiffusion.safetensors`
- `~/Models/JuggernautXL/config/model_index.json`
- the remaining SDXL config/tokenizer JSON/TXT files below `config/`

Install or upgrade with:

```bash
bash scripts/setup-juggernaut-xi
```

To remove the previous Krea 2 Turbo and Realism-LoRA Hugging Face caches
after a successful XI installation:

```bash
bash scripts/setup-juggernaut-xi --remove-krea
```

Juggernaut XI is gated on Hugging Face. Accept the repository terms first
and authenticate locally with `hf auth login`. The setup script downloads
the new checkpoint to a temporary directory, verifies it, preserves or
creates the local SDXL configuration, and only then removes the old
Juggernaut checkpoint. This avoids leaving the image runtime without a
working checkpoint after a failed download.

## Production defaults

The `juggernaut-xl` SDXL registry entry uses:

- scheduler: `dpmpp-2m-karras` (DPM++ 2M Karras)
- standard steps: `30`
- quality steps: `30`
- standard CFG/guidance: `5.0`
- quality long edge: `1216`
- portrait benchmark canvas: `832x1216`
- negative prompt: empty unless a specific defect needs to be suppressed

RunDiffusion recommends 30–40 steps and CFG 3–7 for XI, so the existing
30-step / CFG 5 baseline remains inside the official range while preserving
the local performance profile already validated on Apple Silicon.

`dpmpp-2m-sde-karras` remains available for controlled A/B testing, but
is not the production default.

## Photorealistic people

When the `juggernaut-xl` entry is selected, MLX Nobby keeps the existing
photorealism prompt safeguards for skin texture, facial asymmetry, eyes,
hair, fabric, plausible lighting, tonal variation, and restrained
post-processing. Explicit user prompts and explicit negative prompts still
take precedence.

Automatic Real-ESRGAN post-processing remains disabled in production
quality mode. Upscaling stays an explicit user action through **Bild
verbessern**.

## License

Juggernaut XI v11 is published under CC BY-NC-ND 4.0. Local personal use is
compatible with that license; commercial use requires separate permission
or licensing from RunDiffusion.
