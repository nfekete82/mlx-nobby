# Multi-Image-to-Video

Enter a video request in the chat composer. In the existing video settings,
enable **Multi-Image-to-Video** and select 2–5 PNG, JPEG or WebP images. Current
image attachments are preselected. Add uploads or images from the media library,
drag cards to reorder them, or use the arrow buttons / Alt+ArrowLeft/Right.
Each card can be replaced or removed. Edit the video prompt before creating.
The interface follows the current German or English language setting.

The existing Fast, Standard, Quality, format and profile controls still apply.
The T2V-only Preview preset is rejected for multi-image video. Single-image I2V
and text-to-video keep their existing behavior. The result uses the existing
chat video player, download action and persistent media library registration.

## A: Native keyframe animation

The locally installed `ltx-pipelines-mlx` **0.16.3**, revision
`ae3b7ea9583db775bd4a1dfb506fb789585021e7`, supports repeatable
`--image PATH FRAME_IDX STRENGTH` arguments. The equivalent Python API is
`DistilledPipeline.generate_and_save(images=[ImageConditioningInput(...)])`.
The Nobby worker forwards this list to the existing two-stage distilled pipeline
with low-memory operation and low-RAM streaming.

The UI distributes images evenly from pixel frame 0 to `frames - 1`, including
interior anchors. The API also accepts strictly increasing explicit
`frame_index` values and a `strength` in `[0, 1]`. All images use the same resize
mode and target resolution. Frame 0 replaces the first latent frame; later
images guide generation through `VideoConditionByKeyframeIndex` in both stages.
They are conditioning anchors, so exact reproduction of later images is not
guaranteed. This feature does not use the separate generated-keyframe-slot API.

Capabilities are checked from the installed runtime source without loading a
model. If the API is unavailable, native mode is disabled and rejected by the
service. Scene composition remains available with the MLX provider. No additional
models or modifications to the installed LTX runtime are needed.

## B: Join scenes

One I2V segment is generated per image, sequentially inside one existing video
job and one coordinator lease. **The selected duration is per scene**: three
images at 5 seconds produce approximately 15 seconds of video. All segments use
the same prompt, dimensions, FPS, quality and profile; seeds increment per scene.
The MP4 uses straight cuts, H.264/yuv420p and AAC at 48 kHz. Audio is resampled
and concatenated; a silent segment is filled with silence. Each scene is trimmed
to its selected duration to avoid repeating the extra endpoint frame.

The existing FIFO media queue, cancellation and runtime memory admission apply.
No image or video models are loaded by the composition helper. ffmpeg is
cancellable and has a ten-minute timeout; native generation retains its two-hour
per-segment timeout. The existing resource coordinator releases competing idle
runtimes and restores chat when memory permits.

Completed segments are checkpointed under the existing video job directory,
`video-jobs/segments/<native-job-id>/`. After a failure, cancellation or service
restart, **Reuse completed scenes · Retry** queues a new job and copies verified
completed segments. It rejects changes to settings, source files, chat identity
or the resolved model. Partial segments are removed. Successful jobs remove
their own checkpoints; failed job checkpoints remain durable for future retries.
The final MP4 follows the existing media lifecycle.

## Validation

`tests/test_multi_image_video.py` covers input limits, managed source resolution,
frame indices, provider forwarding, unsupported runtimes, cancellation, retry
validation and real ffmpeg composition with mixed audio. The two browser cases
in `tests/e2e/test_multi_image_video.py` run at desktop and mobile sizes and cover
reordering, replacement, removal, library selection, mode capability checks,
limits and delivery to the existing player. Existing video/provider/queue tests
are run as regressions. Live test details are recorded separately in the release
report; CPU and fixture tests alone do not prove model generation quality.
