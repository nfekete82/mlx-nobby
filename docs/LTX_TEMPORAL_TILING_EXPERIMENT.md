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

## Safeguards and limitations

- The script does not install packages, modify the worker, change model weights, overwrite videos, change the current Git branch or restart services.
- It checks for active MLX-Nobby video jobs, a valid CLI, macOS, model files, and memory/swap telemetry.
- A minimum 30% system free memory is required to start.
- Every two seconds it monitors free memory and swap and stops its own process group on below 12% free, more than 3 GiB additional swap, or 60 minutes elapsed.
- The guard is best effort: extremely fast Metal memory spikes may occur before a sample and cause an OOM.
- This direct CLI smoke test does not acquire MLX-Nobby's runtime coordinator lease. Do not use the UI to start any other model workload while the test is running.
- CPU unit tests only validate command construction and safety code; they do not prove GPU compatibility or measured quality.
- Compare identity stability, pose, camera steadiness, temporal seams, motion, render time and swap. Tiling changes the attention computation and cannot guarantee identical output to an untiled render.
- If the test fails, do not change the production 5-second cap.

Upstream reference: https://github.com/dgrauet/ltx-2-mlx/blob/v0.16.3/docs/PIPELINES.md
