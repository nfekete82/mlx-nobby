# Juggernaut XL Ragnarok defaults

Profile defaults in `quality_profiles.py` for the opt-in `juggernaut-xl` SDXL
registry entry. A compatible local checkpoint is required; the registry
provides a suggested path but does not imply the model is installed:

- scheduler: `dpmpp-2m-karras` (DPM++ 2M Karras)
- standard steps: `30`
- quality steps: `30`
- standard CFG/guidance: `5.0`
- quality long edge: `1216` (native render, no automatic 2× upscale)
- portrait benchmark canvas: `832x1216`
- negative prompt: empty unless a specific defect needs to be suppressed

`dpmpp-2m-sde-karras` remains available for controlled A/B testing, but is not the production default.

The 30-step setting is the production default for both standard and quality Juggernaut generation. Local testing showed a measurable runtime cost at 35 steps without a sufficiently consistent visual gain, so the quality profile now spends its extra budget on the native 1216-pixel render rather than additional diffusion steps.

The `832x1216` canvas is the validated portrait benchmark/reference size, not a forced global aspect ratio. Normal image generation should continue to respect the requested composition/aspect ratio.

Automatic Real-ESRGAN `photo-2x` post-processing is disabled for the production image service. In quality mode this keeps Juggernaut's native texture instead of automatically turning a 1216-pixel render into a 2432-pixel image. Upscaling remains an explicit user action through **Bild verbessern**, so resolution enhancement can be requested after evaluating the native result.

## Photorealistic people

When the `juggernaut-xl` entry is selected, these safeguards apply to its SDXL path. The runtime does not silently switch models or override the selected steps/guidance profile.

For photorealistic human prompts only, the agent adds restrained photographic realism anchors for skin texture, pores, facial asymmetry, eyes, hair, fabric, physically plausible light, tonal variation and a lightly unretouched photographic look. This is intended to reduce the waxy/airbrushed appearance that short generic prompts can produce without turning every image request into a long style prompt.

When the user did not provide a negative prompt, the same path adds a narrow defect-oriented negative prompt for waxy/plastic skin, over-smoothing, doll-like faces, CGI/3D-render appearance, synthetic skin, excessive beauty retouching and oversharpening. An explicit user negative prompt always wins and is never replaced by this default.

The translation layer also protects high-value semantic information before the prompt reaches Juggernaut. Explicit gendered subjects such as `Polizistin` are preserved in English, while loss of negations, quoted literals or numeric values causes the safer original prompt to be retained instead of accepting a fluent but semantically incorrect translation.

These prompt safeguards are deliberately separate from sampler tuning. Change scheduler, CFG or step defaults only after a reproducible local quality test rather than using them to compensate for translation or prompt-loss bugs.
