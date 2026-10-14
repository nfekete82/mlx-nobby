# MFLUX Qwen 2.1 Edit: progress-window timings

The local Mac baseline for three consecutive **Osaurus Qwen-Image-2.1 Edit**
jobs was 57.61, 59.26 and 60.44 seconds (median 59.26 s). All ran with
`low_ram=false` and `mflux_cache_limit_gb=8`. A warm-worker benefit is **not**
yet demonstrated.

## Scope

The existing isolated MFLUX subprocess emits text progress bars (tqdm) and
diagnostic log messages. It does not reliably emit a structured `model_loaded`
boundary through the currently supported CLI. Instead of guessing one, this
patch observes **only** a numeric tqdm `step / total [` marker for
`qwen-image21-edit`, including Osaurus Q4. No raw diagnostic text is stored
or exposed through the Observatory or the report.

New `provider_timing` fields (all milliseconds, null if not observed):

- `tqdm_first_ms`: first observed matching progress frame, measured relative
  to the existing subprocess execution clock.
- `tqdm_first_step`: corresponding progress numerator. Zero indicates the
  0/N frame was actually observed.
- `tqdm_complete_ms`: timestamp the N/N completion frame was observed.
- `tqdm_window_ms`: difference between completion and first frame, **only**
  if the first observed frame was 0/N **and completion was seen in a later
  polling pass**. Buffered 0/N .. N/N output arriving together gives null
  instead of a misleading near-zero duration.

These are best-effort **observer-side output timestamps** (up to the existing
0.5-second polling delay per event); they are *not* exact CPU/Metal GPU stage
markers. Some CLI builds suppress tqdm or buffer output, in which case these
fields remain null. Do not infer precise model loading time by subtraction.

## Validation and safety

- No changes to prompts, input/output files, image settings, precision,
  quantization, cache settings, low-RAM flags, model reuse or active jobs.
- No changes to existing 90% RAM admission, 20 GB headroom policy, 24 GiB
  process RSS cap, cancellation, subprocess timeout or resource coordinator.
- Unit tests use simulated progress bars and silent subprocesses, and ensure
  the read-only Observatory and model-filtered report only return allowlisted
  numeric measurements.

## After deployment

On an idle Mac, perform 3 **new** consecutive comparable edits via Nobby, with
identical reference image(s), prompt, seed, steps, dimensions and guidance.
Then run:

```bash
cd ~/mlx-web
python3 scripts/report-image-edit-baseline.py \
  --model mflux-osaurus-qwen-image-2.1-edit --samples 3 \
  --output artifacts/performance/qwen21-phases.json
```

Compare `process_wall_ms`, `first_output_ms`, `tqdm_first_ms`,
`tqdm_first_step`, `tqdm_complete_ms`, and `tqdm_window_ms` for each
run. A follow-up report extension also shows the content-free numeric
`steps`, `width`, `height`, `guidance`, `reference_count`, plus
**explicit** `use_step_cache` and `use_kv_cache` flags for an apples-to-apples
check. A null cache flag means the flag was omitted, **not** that the model
necessarily disabled that feature; the installed MFLUX CLI may have defaults. If the progress loop occupies most of wall time, priority should be
inference efficiency (with output-quality validation), not a persistent
worker. If measured pre-progress overhead is consistently large, a **separate**
opt-in warm-worker experiment may be worth evaluating, subject to resident
memory profiling and all existing safeguards.
