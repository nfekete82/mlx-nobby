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

## Image jobs and iterative editing

Image generation and image editing use the same asynchronous lifecycle:

`queued -> loading -> running -> saving -> completed`

`failed` and `cancelled` are terminal states.

The image service is the source of truth for job state. The browser displays only provider-reported progress and does not invent synthetic steps or percentages.

Active jobs can be cancelled. A cancelled job creates no artifact and does not replace the previously active image artifact.

## Browser reload recovery

Active `image_generate` and `image_edit` jobs can resume after a browser reload. Persisted session state identifies the candidate job, but recovery always asks the image service for the current server-side state first.

Recovery never starts a replacement job. Completed jobs are finalized exactly once.

## Iterative image artifacts

A completed image generation or edit becomes the active image artifact of the session. A following edit can use that artifact as its source image.

Relevant regression suites include:

- `tests/test_image_runtime.py`
- `tests/test_image_edit.mjs`
- `tests/test_image_job_resume.mjs`
- `tests/test_multi_image_vision.mjs`
