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
