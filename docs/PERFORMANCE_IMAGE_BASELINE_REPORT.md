# Image Edit Baseline: Real Nobby Jobs

This read-only report complements the CLI-only MLX-Gen benchmark and the
startup telemetry from PR #219. **It does not generate images or change model
residency.** It queries the existing local Performance Observatory and completed
image-job records on the Agent and writes a content-free JSON summary.

## Controlled local comparison

After PR #219 has passed CI, merged and its image service code has been deployed
to the actual service installation (normally `~/mlx-web`), complete three real
image edits in Nobby, sequentially, with:

- The same Qwen Image Edit model and source image
- The same prompt, image dimensions, step count, guidance and seed
- No concurrently active video, chat inference or other heavy media jobs

Then collect the last three completed image jobs:

```bash
cd ~/mlx-web
python3 scripts/report-image-edit-baseline.py --samples 3 \
  --output artifacts/performance/image-edit-job-baseline.json
```

It reports median queue wait, generation and total time, plus available
`provider_timing` and native image `performance_timings`. All missing values
remain `null`, not zero. The report intentionally contains no prompts, chat
IDs, file paths, image bytes or job IDs. The tool does not assert the last three
jobs were identical; the operator must control that manually.

If the image service is still using code from before PR #219,
`process_spawn_ms`, `first_output_ms` and `fresh_process` may be absent.
Restart only when existing image jobs are idle, after deploying changes to the
**service working directory**, not merely a separate Git worktree.

The existing CLI-only benchmark `scripts/benchmark-image-edit-mlxgen.py`
measures a different path; do not mix its wall time with end-to-end Nobby time.
Neither baseline alone proves that a warm worker will improve performance.

## Safety

The script only makes loopback HTTP GET requests, does not touch images or jobs,
and does not alter RAM admission (90%), the image process cap (24 GiB), image
quality, backend settings, timeouts, or media lifecycle. Manual real edits still
use Nobby's coordinator and memory admission. Reports stay local.
