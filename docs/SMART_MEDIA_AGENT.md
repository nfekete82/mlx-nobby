# Smart Media Agent (Qwen, opt-in)

**Status:** initial integrated implementation, not merged to `main`.

## User experience

The existing image/video quality dialog now offers **Smart Media · Qwen** (enabled by default, disable to use Direct mode). The preference is local to the browser and does not alter Qwen's chat role or other models.

1. Write a natural request in German or English (e.g. “Erstelle ein cooles Bild einer blonden Frau auf dem Fahrrad”).
2. MLX-Nobby's deterministic media-intent router selects the authorized action and binds the uploaded or selected source, if any.
3. The existing quality dialog controls model, quality, duration, format and image/video profile.
4. With Smart Media enabled, the agent calls the locally configured **chat** model (Qwen3.8 on the test machine) for one strict JSON plan.
5. A validated English prompt and an optional enabled-image-model recommendation go into **existing** image/video job APIs. Job source, action, quality, profile, duration and explicitly selected model remain unchanged.
6. If local Qwen or the planning endpoint fails, the request uses Direct mode. The plan cannot dispatch jobs directly.

### Supported in this version

| Input | Existing operation | Smart Media contribution |
| --- | --- | --- |
| Text + image request | `image_generate` | Optimized T2I prompt; enabled model if Auto |
| Uploaded/selected image + edit | `image_edit` | Conservative change prompt; enabled edit model if Auto |
| Image + request for similar person | Existing reference-mode route | Prompt preserving intended resemblance |
| Text + video request | `video_generate` | Motion/camera prompt for LTX; quality/duration preserved |
| Image + video request | `video_animate` | Prompt preserving source identity and framing |

### Unchanged for this first release

- Talking Photo (requires a separate voice/text/audio/image payload and job lifecycle).
- Dedicated image-upscale menu, multi-image video storyboard UI and video-to-video editor.
- Underlying model downloads and global model selections.
- Existing direct mode, cancellation and worker APIs.

These dedicated workflows need their own source-binding, media-job statuses and output bridges before a single chat entry point can safely dispatch them. They must not be presented as implemented until real end-to-end tests exist.

## Backend API

`POST /api/mlx/chat/media/plan` (web bridge), forwarding to `POST /api/chat/media/plan` (local Agent).

Example:

```json
{
  "prompt": "Erstelle eine blonde Frau auf einem Fahrrad",
  "target": "image",
  "source_kind": "none",
  "selected_model": "auto"
}
```

Result:
```json
{
  "target": "image",
  "mode": "smart",
  "prompt": "Photorealistic ...",
  "model": "juggernaut-xl",
  "negative_prompt": ""
}
```

The endpoint **does not start a job**. Existing `/api/mlx/chat/actions/route` and `/api/mlx/chat/actions` own authorization and dispatch. The source media metadata never becomes a machine-proposed arbitrary local file path. Compiled image prompts go in `image_options.prompt`, video prompts in `video_options.prompt`. `request.prompt` remains the literal user instruction. Qwen picks only from enabled server-side image model IDs. Video uses the existing LTX runtime.

## Tests

```bash
python3 -m pytest -q tests/test_smart_media_agent.py tests/test_media_intent.py
node tests/test_smart_media_ui.mjs
node tests/test_image_edit.mjs
node tests/test_media_quality.mjs
```

After all tests pass and no media job is active, deploy the **web container and Agent** using the existing scripts. Hard-refresh the browser. Check Smart / Direct for T2I, reference-edit and i2v; ensure a manually selected model always wins. Verify results in real job metadata before merging to main.
