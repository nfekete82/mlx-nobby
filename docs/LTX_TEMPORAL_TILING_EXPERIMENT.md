# LTX 2.5 1080p temporal/spatial tiling: isolated smoke test

Status: experimental, manual Mac run; no production settings changed.

## Goal

Check whether the pinned LTX-2-MLX CLI can generate 6 seconds (145 frames) at 1920 x 1088 and 24 fps on a 48 GB Mac using temporal and spatial tiles. Tiles split the transformer computation inside one generation. This is NOT lossless 2-second rolling video extension and is not guaranteed to preserve full-attention quality.

The stable LTX-2-MLX v0.16.3 CLI supports:
- --tile-frames 2: two temporal tiles (NOT two seconds);
- --tile-spatial 2: 2 x 2 spatial tiles;
- --tile-overlap 2: overlap of token-grid areas;
- --low-ram: memory-efficient model weight streaming.

The normal 1080p 5-second API limit stays unchanged.

## Run on the Mac

Stop GPU-heavy tasks first; do not render via the UI at the same time.
In your MLX-Nobby repository (usually ~/mlx-web):

    cd ~/mlx-web
    git fetch origin feat/ltx-1080p-temporal-tiling-smoke-20261101
    git show FETCH_HEAD:scripts/benchmark-ltx-1080p-tiling.py > /tmp/ltx-1080p-tiling-test.py

First inspect the dry-run command:

    python3 /tmp/ltx-1080p-tiling-test.py

Then start the 6-second experiment:

    python3 /tmp/ltx-1080p-tiling-test.py --run

The report, runtime log and MP4 (if successful) are stored in a new
timestamped folder under ~/.local/share/mlx-nobby/tiling-experiments/.

Once six seconds works, test eight:

    python3 /tmp/ltx-1080p-tiling-test.py --run --duration 8

For an untiled 5-second reference (same prompt and seed):

    python3 /tmp/ltx-1080p-tiling-test.py --run --duration 5 --tile-frames 1 --tile-spatial 1

## Image-to-video identity experiment

A 6-second 1080p text-to-video render with 3 temporal and 2x2 spatial tiles
completed on the M5 Max with the chat runtime stopped, but the person visibly
changed identity. To distinguish arbitrary T2V faces from temporal-tiling
identity drift, the benchmark now accepts a single **local** reference image.

Choose a clear **photo of one adult** with the entire intended subject visible,
preferably already composed near the 16:9 output framing. Use PNG or JPEG (or
WebP); export HEIC before using. A different aspect ratio may lead to cropping
when LTX prepares the reference image. The test does not alter the input file.

Example, replacing the path with an actual existing file on your Mac:

    BILD="$HOME/Desktop/testperson.jpg"
    test -f "$BILD" || echo "Image missing; choose the correct path"

Refresh the isolated script, without changing your current git branch:

    cd ~/mlx-web
    git fetch origin feat/ltx-1080p-temporal-tiling-smoke-20261101
    git show FETCH_HEAD:scripts/benchmark-ltx-1080p-tiling.py > /tmp/ltx-1080p-tiling-test.py

Verify the CLI parameters first, without rendering:

    python3 /tmp/ltx-1080p-tiling-test.py --image "$BILD" --duration 6 --tile-frames 3 --tile-spatial 2

If MLX-Nobby chat has already been safely stopped, and no other model job is
active, render the proven RAM-friendly tiling setup:

    python3 /tmp/ltx-1080p-tiling-test.py --run --image "$BILD" --duration 6 --tile-frames 3 --tile-spatial 2 --tile-overlap 2

The image is referenced locally as a full-strength frame-0 anchor with CRF 0
(no additional H.264 recompression of the source for conditioning); no images
are uploaded. With --image, a neutral low-motion identity prompt is selected
automatically. The source path and SHA-256 are included in the private local
report so repeat runs can be compared. This is **only a first-frame anchor**,
not a guarantee of constant identity throughout the entire video.

**What to look for:** the very first generated frame should resemble the
reference photo. Check face, hair, body, clothes and camera framing at 1, 2,
3, 4, 5 and 6 seconds. If identity changes after a particular point, note the
time. Distinguish continuous identity drift from sudden temporal-tile seams.

Optional 5-second reference, using the same image/prompt/seed/tile settings:

    python3 /tmp/ltx-1080p-tiling-test.py --run --image "$BILD" --duration 5 --tile-frames 3 --tile-spatial 2 --tile-overlap 2

The 5-second and 6-second results are **not** expected to be frame-identical:
duration changes the model's generation even with the same seed. If identity
drifts in the six-second render, an additional 6-second run with
--tile-frames 2 can isolate temporal tile-count effects, if sufficient RAM.

## Controlled identity failure diagnosis (after first 1080p I2V)

A 6-second 1080p 16:9 I2V run with 3 temporal and 2x2 spatial tiles
completed without swap growth when chat was stopped. Visual inspection
found a recognizable person for approximately 1 second, followed by
identity loss and a four-face 2x2 grid around 2 seconds. This is an
observed failure, **not a proven root cause**. The reference image
is portrait (1097x1434) while the failed output was landscape
(1920x1088), which also changes the framing.

The benchmark now accepts --resolution 720p and --aspect-ratio 9:16
(704x1280, consistent with MLX-Nobby's production geometry).
Keep the source photo, seed, prompt, duration and geometry constant
for all A/B runs. **Do only the first run initially.**

    cd ~/mlx-web
    git fetch origin feat/ltx-1080p-temporal-tiling-smoke-20261101
    git show FETCH_HEAD:scripts/benchmark-ltx-1080p-tiling.py > /tmp/ltx-1080p-tiling-test.py

    BILD="$HOME/Downloads/Julia_Gerber.png"

    # Control: 720p portrait, 6 seconds, untiled in both dimensions
    python3 /tmp/ltx-1080p-tiling-test.py --run \
        --image "$BILD" --resolution 720p --aspect-ratio 9:16 \
        --duration 6 --tile-frames 1 --tile-spatial 1 \
        --tile-overlap 2 --seed 42

If the untiled clip is stable, compare one variable at a time:

    # Spatial tiling only (2x2), no temporal tiling
    python3 /tmp/ltx-1080p-tiling-test.py --run \
        --image "$BILD" --resolution 720p --aspect-ratio 9:16 \
        --duration 6 --tile-frames 1 --tile-spatial 2 \
        --tile-overlap 2 --seed 42

    # Temporal tiling only (3 partitions), no spatial tiling
    python3 /tmp/ltx-1080p-tiling-test.py --run \
        --image "$BILD" --resolution 720p --aspect-ratio 9:16 \
        --duration 6 --tile-frames 3 --tile-spatial 1 \
        --tile-overlap 2 --seed 42

Interpretation:

- If untiled also fails, inspect I2V conditioning, image crop/geometry
  and distilled inference before blaming tiling.
- If spatial-only fails with a 2x2 grid, investigate spatial tiler
  cross-tile context and blending.
- If temporal-only changes identities at temporal boundaries,
  investigate temporal attention context and anchor propagation.
- If both isolated modes work but combined fails, investigate their
  interaction.
- A memory-guard abort is **not** evidence about visual quality.
  Keep the memory watchdog enabled.

The benchmark now refuses to render while the chat runtime listens
on port 8000. It never stops other services automatically. Stop only
an idle chat server using mlx stop before running; mlx start restores it.

Production 1080p limits remain unchanged.

## Safeguards and limitations

- The script does not install packages, modify the worker, change model weights, overwrite videos, change the current Git branch or restart services.
- It checks for active MLX-Nobby video jobs, an active chat listener (port 8000), a valid CLI, macOS, model files, and memory/swap telemetry.
- A minimum 30% system free memory is required to start.
- Every two seconds it monitors free memory and swap and stops its own process group on below 12% free, more than 3 GiB additional swap, or 60 minutes elapsed.
- The guard is best effort: extremely fast Metal memory spikes may occur before a sample and cause an OOM.
- This direct CLI smoke test does not acquire MLX-Nobby's runtime coordinator lease. Do not use the UI to start any other model workload while the test is running.
- CPU unit tests only validate command construction and safety code; they do not prove GPU compatibility or measured quality.
- Compare identity stability, pose, camera steadiness, temporal seams, motion, render time and swap. Tiling changes the attention computation and cannot guarantee identical output to an untiled render.
- If the test fails, do not change the production 5-second cap.

Upstream reference: https://github.com/dgrauet/ltx-2-mlx/blob/v0.16.3/docs/PIPELINES.md
