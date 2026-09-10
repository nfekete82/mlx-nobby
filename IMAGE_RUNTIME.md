# MLX nobby Image-Runtime

The image path is intentionally separate from the LLM model registry:

```text
chat / image action
        |
        v
agent :8010  -- /api/image/* -->  image service :8030
                                      |
                         image-models.json registry
                                      |
                   diffusionkit or mflux provider
                                      |
                         PNG on local disk
```

The native service writes generated files to
`~/.config/mlx-web/images/`. It returns only an image id, path and metadata;
the agent exposes the existing download route and creates the existing chat
artifact. The browser therefore keeps no image bytes in localStorage.

`FLUX.1-schnell` through DiffusionKit remains the enabled legacy fallback.
MFLUX entries are opt-in and are only reported as available when their local
Hugging Face snapshot (or an allowed `~/Models` path) is present. The service
does not download weights. MFLUX 0.19.1 is called through the installed native CLI
(`~/.local/bin/mflux-*`) in a short-lived subprocess with `shell=False`; this
keeps the image runtime isolated from the normal chat/agent Python process and
allows MLX/Metal memory to be released after each request.

The registry is persisted at `~/.config/mlx-web/image-models.json`. Built-in
entries are migrated into an existing registry without overwriting user
choices. The `image` model role in `model-roles.json` stores an image-registry
id (or `auto`) and never resolves through `load_models()` or LLM aliases.

Supported MFLUX command families are selected explicitly by `model_family`:

| Family | Native command |
| --- | --- |
| FLUX.1 | `mflux-generate` |
| FLUX.2 Klein | `mflux-generate-flux2` |
| Z-Image | `mflux-generate-z-image` |
| Z-Image Turbo | `mflux-generate-z-image-turbo` |
| Qwen Image | `mflux-generate-qwen` |

Model-specific guidance/step limits and up to eight LoRAs are validated by
the registry before a provider process is started. No prompt keyword filter is
added by the runtime.
