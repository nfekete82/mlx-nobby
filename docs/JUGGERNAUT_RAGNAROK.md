# Juggernaut XL Ragnarok defaults

MLX Nobby keeps the stable registry ID `juggernaut-xl` and the local
directory `~/Models/JuggernautXL` for backward compatibility, but the
supported checkpoint is now **Juggernaut XL Ragnarok**.

Ragnarok is the final SDXL Juggernaut release. The author states that it is
a CivitAI-exclusive release; the last official Juggernaut XL release on
Hugging Face remains XI v11.

Expected local layout:

- `~/Models/JuggernautXL/juggernautXL_ragnarok.safetensors`
- `~/Models/JuggernautXL/config/model_index.json`
- the remaining SDXL config/tokenizer JSON/TXT files below `config/`

Install or upgrade with:

```bash
bash scripts/setup-juggernaut-ragnarok
```

To also remove the temporary Juggernaut Z test entry and the very large
Hugging Face cache downloaded during evaluation:

```bash
bash scripts/setup-juggernaut-ragnarok --remove-juggernaut-z
```

The setup downloads CivitAI model version `1759168`, verifies the published
SHA256
`dd08fa32f98d05a2443ca1419e46df1575a0811f6e3b246d9dd47ff20f5eb66a`,
preserves or creates the local SDXL configuration, unloads the image runtime
before replacement, and only then removes the previous Juggernaut checkpoint.

The legacy `scripts/setup-juggernaut-xi` command is retained as a wrapper so
old local notes and automation still install Ragnarok.

## Production defaults

The `juggernaut-xl` SDXL registry entry uses:

- scheduler: `dpmpp-2m-karras` (DPM++ 2M Karras)
- standard steps: `30`
- quality steps: `30`
- standard CFG/guidance: `5.0`
- quality long edge: `1216`
- portrait benchmark canvas: `832x1216`
- negative prompt: empty unless a specific defect needs to be suppressed

The 30-step / CFG 5 baseline keeps the existing Apple Silicon performance
profile while remaining suitable for Ragnarok. Scheduler benchmarking remains
available through `scripts/benchmark-juggernaut.py`.

## Photorealistic people

When the `juggernaut-xl` entry is selected, MLX Nobby keeps the existing
photorealism prompt safeguards for skin texture, facial asymmetry, eyes,
hair, fabric, plausible lighting, tonal variation, and restrained
post-processing. Explicit user prompts and explicit negative prompts still
take precedence.

Automatic Real-ESRGAN post-processing remains disabled in production quality
mode. Upscaling stays an explicit user action through **Bild verbessern**.

## Source

- CivitAI model version: `1759168`
- checkpoint: `juggernautXL_ragnarok.safetensors`
- checkpoint size: approximately 6.62 GB
- SHA256: `dd08fa32f98d05a2443ca1419e46df1575a0811f6e3b246d9dd47ff20f5eb66a`
