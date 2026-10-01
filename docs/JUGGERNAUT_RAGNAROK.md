# Juggernaut XL Ragnarok defaults

Validated local production baseline for `~/Models/JuggernautXL/juggernaut-xl-ragnarok.safetensors` on Apple Silicon:

- scheduler: `dpmpp-2m-karras` (DPM++ 2M Karras)
- standard steps: `30`
- standard CFG/guidance: `5.0`
- portrait benchmark canvas: `832x1216`
- negative prompt: empty unless a specific defect needs to be suppressed

`dpmpp-2m-sde-karras` remains available for controlled A/B testing, but is not the production default.

The 30-step setting is the production default. A 35-step run remains available as an explicit quality choice, but local testing showed a measurable runtime cost without a sufficiently consistent visual gain to replace the 30-step standard.

The `832x1216` canvas is the validated portrait benchmark/reference size, not a forced global aspect ratio. Normal image generation should continue to respect the requested composition/aspect ratio.

## Photorealistic people

Juggernaut remains the production model for the SDXL path. The runtime does not silently switch models or override the selected steps/guidance profile.

For photorealistic human prompts only, the agent adds restrained photographic realism anchors for skin texture, pores, facial asymmetry, eyes, hair, fabric, physically plausible light, tonal variation and a lightly unretouched photographic look. This is intended to reduce the waxy/airbrushed appearance that short generic prompts can produce without turning every image request into a long style prompt.

When the user did not provide a negative prompt, the same path adds a narrow defect-oriented negative prompt for waxy/plastic skin, over-smoothing, doll-like faces, CGI/3D-render appearance, synthetic skin, excessive beauty retouching and oversharpening. An explicit user negative prompt always wins and is never replaced by this default.

The translation layer also protects high-value semantic information before the prompt reaches Juggernaut. Explicit gendered subjects such as `Polizistin` are preserved in English, while loss of negations, quoted literals or numeric values causes the safer original prompt to be retained instead of accepting a fluent but semantically incorrect translation.

These prompt safeguards are deliberately separate from sampler tuning. Change scheduler, CFG or step defaults only after a reproducible local quality test rather than using them to compensate for translation or prompt-loss bugs.
