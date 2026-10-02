# MFLUX provider compatibility

The image adapter checks the actual local CLI contract before reporting a model
as available or starting its provider. `mflux_capabilities.py` caches offline
`--help` probes per executable and reads the version from that executable's tool
environment. `/models` exposes the version, supported flags and availability
reason. No model weights are downloaded or modified by these checks.

The reviewed MFLUX 0.19.1 and 0.20.0 Qwen Edit commands do not accept
`--canvas-policy`; the service already resolves dimensions from the source image.
`--json-events` is optional and is passed only when advertised. Otherwise jobs
report coarse generation phases. Required generation flags, requested
quantization and enabled LoRAs are checked before execution.

Qwen's supported loader expects an unquantized text/vision encoder. Availability
checks read local safetensors headers and reject packed quantized encoder weights
before runtime; tensor data is not loaded. Malformed headers are unavailable.

Both image routers reject an incompatible default model when no compatible
generator exists. Failed image jobs expose `error_code`, `error_provider`,
`error_model` and `error_detail_safe`. Provider process output remains in a local
`.provider.log`; API diagnostics retain only safe metadata, not prompts, private
paths or tracebacks. The repository dependency pin remains unchanged.
