# MFLUX provider compatibility

The image adapter checks the actual local CLI contract before reporting a model
as available or starting its provider. `mflux_capabilities.py` caches offline
`--help` probes per executable and reads the version from that executable's tool
environment. `/models` exposes the version, supported flags and availability
reason. No model weights are downloaded or modified by these checks.

The supported standalone runtime is pinned to **MFLUX 0.20.0**. The host helper
`scripts/setup-mflux-mlx` backs up the previous uv-tool state, installs the pin
and validates the CLI entry points used by MLX Nobby.

Qwen Image 2.1 uses the dedicated `mflux-generate-qwen-2.1` command. Nobby's
built-in entry is opt-in, Q8, and uses the upstream 40-step guidance-free
sampling contract (`guidance=1.0`). Boogu Image Turbo uses
`mflux-generate-boogu`; guidance is distilled into that model, so the provider
does not pass `--guidance`. Its fast profile uses 4 steps at 768 px and its
1024 px standard/quality profiles use 8 steps.

Krea 2 remains intentionally absent from the Nobby registry. Old persisted Krea
entries are removed during registry migration and are not restored by the MFLUX
0.20 update.

Qwen Edit does not use the former `--canvas-policy`; the service resolves
dimensions from the source image. `--json-events` is optional and is passed only
when advertised. Otherwise jobs report coarse generation phases. Required
generation flags, requested quantization and enabled LoRAs are checked before
execution.

Qwen's supported loaders keep the text/vision encoder unquantized. Availability
checks read local safetensors headers and reject packed quantized encoder weights
before runtime; tensor data is not loaded. Malformed headers are unavailable.

Both image routers reject an incompatible default model when no compatible
generator exists. Failed image jobs expose `error_code`, `error_provider`,
`error_model` and `error_detail_safe`. Provider process output remains in a
local `.provider.log`; API diagnostics retain only safe metadata, not prompts,
private paths or tracebacks.
