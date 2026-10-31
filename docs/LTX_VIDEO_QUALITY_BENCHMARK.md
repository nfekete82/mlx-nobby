# Reproducible LTX rolling quality diagnostics

The benchmark is offline and CPU-only. It never submits video jobs, loads model
weights, downloads detectors, or retries a GPU render. Generated media and local
reports stay outside Git under `artifacts/`.

## Run

Use the existing image service environment for NumPy, SciPy and Pillow. The
production service does not gain these dependencies. FFmpeg/ffprobe must be on
PATH. Optional Apple Vision face geometry uses macOS's installed framework:

```sh
swiftc -module-cache-path /private/tmp/ltx-swift-cache \
  scripts/video-face-landmarks.swift -o /private/tmp/video-face-landmarks
image-venv/bin/python scripts/benchmark-video-quality.py \
  before=/absolute/before.mp4 after=/absolute/after.mp4 \
  --job before=/absolute/before-job.json --job after=/absolute/after-job.json \
  --vision-helper /private/tmp/video-face-landmarks \
  --out artifacts/ltx-comparison-unique-name
```

Omit `--vision-helper` on other platforms. The helper may require execution
outside an application sandbox because Vision's system services are unavailable
inside it. A failed optional detector is reported as `unavailable`, and does not
invalidate the technical measurements. Each output label directory must be new;
existing reports are not overwritten. Inputs are read-only.

Open `index.html` locally for the comparison table, native frames, contact
sheets, face crops, original source, video players, exact seam windows, and
geometry observations. Video/source files are copied into this private report
so it remains usable locally without the original service paths. `report.json`
contains per-frame measurements, video SHA256, FFmpeg version, effective job
settings, source/prompt hashes and available memory telemetry. Original prompts
and upload paths are omitted from this report. Review frames and landmarks are
private local artifacts; do not commit them.

## What is measured

- Video/audio duration and start/end offsets; frame count, actual FPS and
  presentation timestamps. Nonpositive or irregular frame intervals are listed.
- Exact adjacent duplicate frames via hashes of native decoded YUV planes.
- Adjacent-frame luma SSIM using an 11×11 Gaussian window, sigma 1.5, K1 .01,
  K2 .03, population covariance, five-pixel border excluded.
- Adjacent mean absolute luma change and variance of the discrete Laplacian.
  These analysis metrics use area downsampling to a maximum side of 512 px,
  explicitly recorded in the report; only two image arrays are retained.
- Exact join pairs at frames 144→145 and 192→193, with a ±3-frame local window
  and change magnitude relative to the median away from either join.
- Requested times 0, 3, 5.9, 6.1, 7.9, 8.1, 9.9 s, plus both exact join pairs.
  Nearest decoded timestamps and actual frame numbers are shown, not invented
  exact samples between frames.
- Optional CPU Vision landmarks at those sparse samples: face count, confidence,
  yaw/roll, interocular distance/face width, mouth width/face width and eye height/
  width. Geometry uses native pixel aspect ratios. Differences between sample
  observations are exported without an arbitrary identity acceptance threshold.
- Job generation time and persisted before/peak/after and stage memory readings.
  `scripts/monitor-video-quality-run.py JOB_ID --out new-file.jsonl` can record
  two-second macOS budget snapshots for an existing job, with a fixed deadline.
  This monitor is read-only; service guards remain responsible for stopping work.

The 6+2+2 plan has 145+48+48 = **241 frames**. Its intended 10 s motion timeline
has a 10.041667 s video stream: the inclusive initial frame occupies one display
interval. At zero initial PTS, first appended frames are at 6.041667 and 8.041667
s. A muxer offset must also be included when analyzing older files.

## Interpretation and limits

SSIM compares already decoded images; it cannot attribute a change to the VAE,
the denoiser, motion or codec without an isolated experiment. High temporal SSIM
can reward frozen video. Laplacian variance can reward noise and sharpening.
Unaligned frames, framing differences and black bars confound cross-video
comparisons. A 540p landscape render is historical context, not a controlled
720p portrait baseline. Full-reference codec SSIM uses identical source frames
and is a separate preservation experiment; see the
[FFmpeg SSIM documentation](https://ffmpeg.org/ffmpeg-filters.html#ssim).

Face geometry changes during desirable blinking, smiling, turning and detector
jitter. Multiple/missing faces are retained as observations; the benchmark does
not silently select a different identity. There is no face embedding, biometric
identity score, motion-compensated optical-flow score, learned perceptual-quality
score, or automatic quality verdict. Stream offsets measure container timing,
not audiovisual semantic alignment or lip sync. Sparse landmark samples do not
prove natural blinking between them. Inspect native eye crops and play both
videos before claiming a visible improvement.

## Verification

```sh
.test-venv/bin/python -m pytest -q tests/test_video_rolling.py tests/test_video_segmented.py
image-venv/bin/python -m unittest tests/test_video_quality_benchmark.py -v
node tests/test_video_job.mjs
.test-venv/bin/python -m pytest --e2e -q tests/e2e/test_video_rolling_quality.py
```

These tests include exact decoded-pixel preservation, actual audio/video clocks,
SSIM behavior, static duplicate detection, optional detector failure, native face
crops, checkpoint cancellation/resume and desktop/mobile settings forwarding.
CPU fixtures do not establish native facial quality.
