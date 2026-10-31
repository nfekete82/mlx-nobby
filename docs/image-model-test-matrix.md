# Image model test matrix

Update this matrix after **every model test**, including unsuccessful trials.
Record the actual test date, checkpoint/version, provider/runtime, Steps/CFG,
resolution and seed where known, plus a short result and an evidence link.
Keep generated/private media outside Git. Do not use the documentation-update
date as a substitute for an unknown render-test date.

Status: `planned` = evaluation intended; `configured` = registry integration
exists but no successful real render is recorded; `tested` = at least one
successful real image generation (not necessarily recommended);
`rejected` = explicitly ruled out.
Configured does not imply installed weights, an enabled model or a GPU test.

Catalog reviewed: **2026-10-27**. Historical feedback below is distinguished
from measurements made with matched settings.

| Model | ID | Provider | Status | Last test / date | Result / short conclusion | Notes / evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Juggernaut XL Ragnarok | `juggernaut-xl` | `sdxl` / Diffusers MPS | `tested` | 2026-10-27, 11:26 CET | Installed, enabled, default retained. Actual Metal load/render passed; valid RGB PNG, 832×1216. Worker 16.378 s; service job 29.901 s. | 35 steps, CFG 5, DPM++ 2M SDE Karras, seed 27102026; retain as default. [Matched smoke comparison and quality observations](CYBERREALISTIC_PONY_V18.md). Existing persisted settings remain 30 steps / CFG 5; this request explicitly used 35. Historical [46 XL jobs](PERFORMANCE_MFLUX_QWEN21_EDIT.md) are a separate, unmatched family-level sample. |
| Lustify / Lustify Endgame | `lustify-endgame-sdxl` (retired historical ID) | `sdxl` (historical comparison) | `tested` | Actual render-test date not recorded; project feedback recorded 2026-10-27 | Tried; visual quality was not convincing and it is not preferred (project feedback, not a quantified benchmark). | Comparison model only, no current built-in. The [retirement documentation](SDXL_MEMORY_SAFETY.md) and `tests/test_lustify_retirement.py` preserve the removal; this catalog does not reintroduce it. |
| CyberRealistic Pony v18.0 CoreShift FP16 | `cyberrealistic-pony-v18` | `sdxl` / Diffusers MPS | `tested` | 2026-10-27, 11:25 CET | Installed, full SHA256 verified, enabled as additional model. Actual Metal load/render passed; valid RGB PNG, 832×1216. Worker 15.607 s; service job 30.001 s. | SDXL / Pony V6 XL architecture. 35 steps, CFG 5, DPM++ 2M SDE Karras, seed 27102026, default penultimate CLIP layer (UI Clip Skip 2). Photographic, fully clothed full-body subject in daylight; apparent age misses the requested 35 years. Retain opt-in; retest broader prompt/age fidelity before preferring it. [Exact checkpoint, artifacts, timings, issues and rollback](CYBERREALISTIC_PONY_V18.md). Factory entry remains disabled for fresh installations. |
| CyberRealistic Z-Image Turbo v7 | — (not registered) | Not configured | `planned` | Not tested | Evaluation pending. | No runtime entry, installed-weight assumption or download is introduced. Do not confuse this planned checkpoint with the existing generic `mflux-z-image-turbo` built-in. |

The 2026-10-27 comparison used identical prompts, negative prompts, seed,
resolution, steps, CFG and scheduler, once per model with a fresh worker.
It establishes successful integration, not a repeatable speed ranking or broad
quality acceptance. Registry/profile/migration and SDXL safety regressions also
passed; CPU-only tests never promote a model to `tested`.

### 2026-10-29: CPU-only lifecycle/provider regression

No image checkpoint was loaded or rendered in this change. The existing SDXL /
Diffusers-MPS and MFLUX provider tests used mocks and isolated CPU workers;
checkpoint installation, architecture selection and registry status remain
unchanged. GPU/load result: not exercised. Render time, resolution, steps, CFG,
scheduler, seed and observed image quality: not applicable to this CPU-only run.
No model is promoted to `tested`, retained or rejected based on these tests;
real GPU cancellation and memory-release behavior still require a deliberate
retest. Initial test failures involved provider mock boundaries after adding
process supervision and were corrected; they are not checkpoint failures.
See [implementation, evidence and limitations](LIFECYCLE_VIDEO_EDIT_RELIABILITY_2026-10-29.md)
and [automated results](lifecycle-video-edit-validation.json).

### 2026-10-29: SDXL guardian/orphan regression (no GPU render)

- Checkpoint under repair: Juggernaut XL Ragnarok, registry ID `juggernaut-xl`,
  version `1759168`, `juggernautXL_ragnarok.safetensors`; expected registry SHA256
  `dd08fa32f98d05a2443ca1419e46df1575a0811f6e3b246d9dd47ff20f5eb66a`.
  Architecture: SDXL; provider: Diffusers/MPS with the existing SDXL worker.
- Installation: local checkpoint presence verified, 7,105,350,162 bytes;
  weights were not read into a model, changed or newly checksummed. Existing
  installation/profile/status are retained.
- Actual test date: 2026-10-29. GPU/model-load result: **not exercised**;
  worker/process tests use isolated CPU processes and mocks. Render time,
  resolution, steps, CFG, scheduler and seed: N/A for this CPU regression.
  Image quality: not assessed; there is no new successful model-render evidence.
- Known issues tested: dead guardian with live child, SIGTERM/SIGKILL, zombies,
  PID reuse, missing/invalid identity evidence, stale registry files, concurrent
  timer/cancel and preservation of the underlying cleanup exception. An initial
  stale-identity expectation was updated to require fail-closed behavior; a
  later queue test needed isolation from an existing scheduler.
- Decision: retain the existing checkpoint, profiles and historical `tested`
  status; **retest real Metal render/cancellation/memory release** before claiming
  production reliability. No model is newly marked `tested` by these regressions.
  [Implementation, observed live-state limits and manual acceptance commands](AUTOMATIC_LONG_VIDEO_SDXL_2026-10-29.md)
  · [CPU regression evidence](automatic-long-video-validation.json).

### 2026-10-31: LTX-2.5 rolling video A/B (video evidence, no image-status promotion)

- Installed checkpoint: `dgrauet/ltx-2.5-mlx-q4`,
  `transformer-distilled.safetensors` (11,320,034,990 bytes); LTX-2.5 22B
  distilled audio/video transformer, int4, native `ltx-mlx` / Apple Metal.
  Runtime 0.18.0, commit `b82b97e3d000e01361f8cfcb745244b15b89a521`.
  Existing local model pack retained; no downloads or installation changes.
- Actual test date: **2026-10-31 CET** (2026-10-30 UTC). Baseline real GPU
  load/render **passed**: job `cb7197efd8000d69bdcc6071`, video
  `672e1f3cbada8eff4e6b456b.mp4`, 704×1280, 241 frames, 24 FPS,
  6+2+2 s rolling with 25-frame context, seed 0, 8+3 distilled steps per
  stage, native LTX-2.5 ancestral sampler/sigma tables; CFG not applicable
  on this distilled path. Stage times: 217.55 / 106.57 / 103.11 s.
- Technical issues: previous intermediate CRF 10 is not pixel-exact; existing
  MP4 concat shifts video start by ~21 ms relative to audio. Facial quality
  requires paired visual review; prompt guidance is not an identity lock.
- Decision: retain the installed model and experimental opt-in; run the one
  remaining authorized matched candidate, then decide from measured evidence.
  No image checkpoint is newly classified as `tested` by a video generation.
- [Benchmark method](LTX_VIDEO_QUALITY_BENCHMARK.md). Final paired results and
  provenance will be recorded in `LTX_QUALITY_REPORT_2026-10-31.md`.

- Candidate attempt `173be32d6f2f2c5c4ce82d98` on the same actual date:
  **failed before inference**, 10.57 s job wall time, zero checkpoints, no
  output video. Process supervision rejected the guardian's startup identity;
  this is not a checkpoint-quality or OOM result. Admission was normal at 82%
  available estimate, swap 7.24 GiB without growth. Requested settings remain
  704×1280 / 24 FPS / 241 frames / seed 0 / 8+3 steps / distilled ancestral /
  CFG N/A. Quality: unassessed. Decision: retain model; investigate startup on
  CPU before one bounded continuation of the unrendered candidate.

- Candidate continuation `cb0127c78f871c3878512788`, **2026-10-31 CET**:
  real GPU load/render **passed**, 420.956 s wall time; stages
  209.97 / 103.81 / 103.34 s. Output `b6731ecfcbbf3114a32b5c01.mp4`,
  704×1280, 241 frames, 24 FPS, seed 0; same installed LTX-2.5 distilled
  checkpoint/provider/runtime as above, 8+3 steps, native ancestral schedules,
  CFG N/A. HF model revision `e9a20add8c5937fcab635fb8e7a52926487a5776`;
  checkpoint SHA256/provenance is recorded in the linked evidence.
- Quality: native face crops remain broadly similar, small eye asymmetry and
  expression drift remain; no substantial visible eye-quality improvement
  established. Exact intermediate YUV transport and zero A/V stream offset are
  demonstrated; no duplicate frames or PTS errors. Candidate active memory
  availability minimum 58%, swap 7.24→7.22 GiB, normal pressure.
- Decision: **retain experimental opt-in and retest facial acceptance** in a
  future authorized latent-carry experiment; no default promotion, no further
  GPU retry and no image-model `tested` status promotion. Exactly two complete
  new videos were produced. [Full report](LTX_QUALITY_REPORT_2026-10-31.md) ·
  [matched measurements and memory evidence](ltx-quality-evidence/comparison.json).

### 2026-10-31: LTX I2V cause isolation, CPU phase

Existing installed `dgrauet/ltx-2.5-mlx-q4` / LTX-2.5 22B distilled int4,
native MLX 0.18.0 at `b82b97e3d000e01361f8cfcb745244b15b89a521`, retained.
Actual test date 2026-10-31 CET. CPU analysis decoded the two existing 704×1280,
241-frame / 24 FPS / seed-0 videos and ran CPU Vision landmarks; **no new GPU
load or generation** in this phase. Native still-preprocessing definitions were
executed on CPU at CRF 18 versus 0, at 352×640 and 704×1280. The pure CPU native
factory contract was checked without importing MLX. Render time, denoising
steps/CFG/scheduler for these CPU probes: N/A; existing videos used 8+3 distilled
ancestral steps, CFG N/A. Pixel preservation improves, generated quality is
unassessed. Decision: retain default preprocessing; configure an API-only
CRF-0 experiment, not a tested quality improvement. No image-model status
promotion. [Cause analysis and evidence](LTX_I2V_CAUSE_ISOLATION_2026-10-31.md).

- Native CRF-0 I2V trial on **2026-10-31 CET**: real GPU load/render passed,
  job `1a5c36b2c257a912fcf29bf5`, output `4b46644eefe0c229ff0c6412.mp4`,
  418.473 s wall time. Same installed LTX-2.5 22B
  distilled int4 checkpoint and pinned 0.18 runtime above; 704×1280, 241 frames,
  24 FPS, seed 0, 8+3 native distilled ancestral steps, CFG N/A. Explicit
  initial still CRF 0 in both spatial stages, normal rolling/audio unchanged.
  Initial native samples still show the long early eye closure; final dense
  assessment pending. Retain default; no quality acceptance or status promotion.

- Soft-guidance-off trial on **2026-10-31 CET**: real GPU load/render passed,
  job `cf06686b4e2819f004233ccd`, output `f56615b625f61f177bd42125.mp4`,
  433.791 s wall time. Same installed LTX-2.5 22B
  distilled int4 checkpoint/provider and pinned 0.18 runtime; 704×1280,
  241 frames, 24 FPS, seed 0, 8+3 ancestral steps, CFG N/A. Native still CRF 18,
  original frame-zero image anchor retained; only existing soft text guidance
  disabled via `identity_lock=false`. Initial motion differs; dense final
  assessment pending. Exactly two new complete videos, no generation retries.
  No automatic quality acceptance or default change.

- Final assessment for these two 2026-10-31 trials: exact installed checkpoint
  `transformer-distilled.safetensors` from `dgrauet/ltx-2.5-mlx-q4`, revision
  `e9a20add8c5937fcab635fb8e7a52926487a5776`, actual previously verified SHA256
  `413479747a7ecd39c71460c3b0e4c872399c64fdaff85f4ef2a28c435a45f21d`.
  No installation/runtime/weight changes. CRF 0 **rejected as an eye-motion fix**:
  initial low-aperture windows 43/21 frames versus 41/21 baseline. Guidance-off
  yields 20/7 frames and visibly earlier reopening, a **limited positive finding
  for this source/seed**, not general identity acceptance. Native join review
  does not establish an isolated identity jump despite lower temporal SSIM.
  Both real videos have 241 frames, no exact duplicates or PTS anomalies,
  aligned A/V stream timing and passing real browser playback. Observed active
  availability minima 67% / 58%, normal pressure; swap stable/decreasing.
  Decision: retain model and default rolling behavior; keep CRF 0 research-only,
  manually review guidance opt-out; no automatic approval or image `tested`
  status promotion. [Final comparative evidence](ltx-i2v-cause-evidence/gpu-comparison.json).
