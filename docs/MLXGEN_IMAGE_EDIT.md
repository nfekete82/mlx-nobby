# Qwen Image Edit 2511 via isolated MLX-Gen

The built-in `mflux-qwen-image-edit-2511` ID is retained for existing user
settings and chat requests, but its **provider is migrated to `mlxgen`**.
The previous MFLUX loader cannot load the prepared AbstractFramework 4-bit
quantized text/vision encoder. Other MFLUX models are unchanged.

## Local prerequisite

Install MLX-Gen in a standalone environment (never force-overwrite the global
`mflux-*` executables):

```sh
uv venv --python python3.13 ~/.local/share/mlx-gen-venv
uv pip install --python ~/.local/share/mlx-gen-venv/bin/python mlx-gen==0.38.0
~/.local/share/mlx-gen-venv/bin/mlxgen --help
```

The default executable is
`~/.local/share/mlx-gen-venv/bin/mlxgen`. Override with
`MLX_IMAGE_MLXGEN_BIN` if needed. The image runtime checks the existing offline
Hugging Face snapshot of `AbstractFramework/qwen-image-edit-2511-4bit`.
Neither readiness checks nor generation perform automatic downloads.

The runtime invokes `mlxgen generate --model AbstractFramework/qwen-image-edit-2511-4bit --image <local
source> --prompt ...` with HF_HUB_OFFLINE=1 and without forcing `--task` or `--i2i-mode`: MLX-Gen
0.38.0 selects the valid Qwen edit handler automatically. Existing per-job
isolation, cancellation, RAM admission, process-RSS bounds, and output
validation remain active. Provider availability proves required files and CLI
exist, **not** successful model loading or image quality.

## Local verification

Run the repository test suite on the feature branch:

```sh
./scripts/mlx test-release
curl -fsS http://127.0.0.1:8030/models | jq '.models[] | select(.id=="mflux-qwen-image-edit-2511") | {provider,enabled,available,availability_note}'
```

If the image service does not auto-reload edited Python modules, restart **only
the idle image service** after checking no image job is active. The final end-to-end
acceptance must include an actual edit request from the Nobby UI; normal image
generation acceptance does not establish that image editing works.

Do not bypass admission limits, delete the existing model cache, or install the
large separate quality model to work around an availability failure.

**Routing regression:** Avoid passing the absolute HF snapshot directory as `--model`:
MLX-Gen 0.38.0 may choose latent img2img instead of Qwen edit and exit 2
with `--image-strength is required`. The repository ID is resolved from the
same existing local cache because `HF_HUB_OFFLINE=1` is set.
