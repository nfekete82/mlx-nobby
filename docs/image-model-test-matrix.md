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

Catalog reviewed: **2026-10-29**. Historical feedback below is distinguished
from measurements made with matched settings.

| Model | ID | Provider | Status | Last test / date | Result / short conclusion | Notes / evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Juggernaut XL Ragnarok | `juggernaut-xl` | `sdxl` / Diffusers MPS | `tested` | 2026-10-27, 11:26 CET | Installed, enabled, default retained. Actual Metal load/render passed; valid RGB PNG, 832×1216. Worker 16.378 s; service job 29.901 s. | 35 steps, CFG 5, DPM++ 2M SDE Karras, seed 27102026; retain as default. [Matched smoke comparison and quality observations](CYBERREALISTIC_PONY_V18.md). Existing persisted settings remain 30 steps / CFG 5; this request explicitly used 35. Historical [46 XL jobs](PERFORMANCE_MFLUX_QWEN21_EDIT.md) are a separate, unmatched family-level sample. |
| Lustify / Lustify Endgame | `lustify-endgame-sdxl` (retired historical ID) | `sdxl` (historical comparison) | `tested` | Actual render-test date not recorded; project feedback recorded 2026-10-27 | Tried; visual quality was not convincing and it is not preferred (project feedback, not a quantified benchmark). | Comparison model only, no current built-in. The [retirement documentation](SDXL_MEMORY_SAFETY.md) and `tests/test_lustify_retirement.py` preserve the removal; this catalog does not reintroduce it. |
| CyberRealistic Pony v18.0 CoreShift FP16 | `cyberrealistic-pony-v18` | `sdxl` / Diffusers MPS | `tested` | 2026-10-27, 11:25 CET | Installed, full SHA256 verified, enabled as additional model. Actual Metal load/render passed; valid RGB PNG, 832×1216. Worker 15.607 s; service job 30.001 s. | SDXL / Pony V6 XL architecture. 35 steps, CFG 5, DPM++ 2M SDE Karras, seed 27102026, default penultimate CLIP layer (UI Clip Skip 2). Photographic, fully clothed full-body subject in daylight; apparent age misses the requested 35 years. Retain opt-in; retest broader prompt/age fidelity before preferring it. [Exact checkpoint, artifacts, timings, issues and rollback](CYBERREALISTIC_PONY_V18.md). Factory entry remains disabled for fresh installations. |
| CyberRealistic Z-Image Turbo v7 | — (not registered) | Not configured | `planned` | Not tested | Evaluation pending. | No runtime entry, installed-weight assumption or download is introduced. Do not confuse this planned checkpoint with the existing generic `mflux-z-image-turbo` built-in. |
| Krea Noct V4 INT8 ConvRot | — (not registered) | Krea-2 / no configured compatible provider | `planned` | 2026-10-29, format/header and CPU contract inspection only | Direct integration blocked: ComfyUI INT8-ConvRot is not the installed MFLUX quantization format. No successful model load or render. | Retest after a compatible verified export and complete components exist. Existing models/defaults retained. [Format evidence](krea-noct-compatibility-2026-10-29.json) · [Blocker and comparison workflow](KREA_NOCT_EXPERIMENT_2026-10-29.md). |

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

### 2026-10-29: Krea Noct compatibility inspection (no GPU render)

- Exact candidate: `Noctaluna/Krea2-Noct-Uncensored`, revision
  `d93fbcb45e6f6995f2ecdd4edfdb1ef12db6e6e4`,
  `KreaNoct_V4_int8_convrot.safetensors`, 13,492,706,520 bytes (12.57 GiB).
  Publisher LFS SHA256: `03622b92c5631870c40426c0dfd3c98b1db33b662140b1e4000210d62f518e2a`;
  full-file checksum was **not** independently verified, since no weight download occurred.
- Architecture: Krea-2-Turbo single-stream MMDiT, Qwen3-VL-4B text encoder,
  Qwen-Image VAE. Provider state: MFLUX 0.22.0 has Krea-2 code, and Diffusers
  0.40.0 has Krea2Pipeline; MLX-Nobby has no configured provider for this
  checkpoint's INT8-ConvRot scales and activation rotations.
- Actual test date: **2026-10-29**. Installation: no candidate checkpoint or
  complete Krea/Noct component directory in the normal model/cache roots; existing Juggernaut checkpoint
  remains present (7,105,350,162 bytes). The initial public metadata request
  hit sandbox DNS restrictions; the authorized retry succeeded. Only metadata
  and the 88,360-byte Safetensors prefix/header were fetched using bounded
  HTTP-206 ranges. Header: 878 tensors, including 224 I8 weight tensors.
- GPU/load result: **not attempted**. Render time, actual render resolution,
  steps, CFG, scheduler and seed: **N/A**. Quality: **not assessed**.
  Planned matched comparison: 832×1216, seeds 27102026/27102027/27102028;
  Noct reference settings 8 steps / CFG 1 / Euler / Simple; Juggernaut 35 steps /
  CFG 4 / DPM++ 2M SDE Karras. These are plans, not render measurements.
- Known blocker: native MFLUX floating-point/MLX-packed loading does not decode
  ComfyUI INT8 scales/ConvRot; casting I8 to BF16 is not dequantization. Complete
  text encoder/VAE/tokenizer assets are also required. Noct-specific instruction
  edit support, actual Metal memory peaks and image quality remain untested.
- Decision: reject direct binding of this artifact to current providers;
  **retest** a compatible export/runtime. Candidate remains `planned`, never
  `configured` or `tested`. Juggernaut, Osaurus Qwen 2.1 and Qwen Image Edit
  registry/profile/default values are unchanged. The accompanying CPU-only
  registry, API, provider and picker regression results are recorded in the
  [experiment report](KREA_NOCT_EXPERIMENT_2026-10-29.md); they do not constitute
  image generation evidence.
- CPU regression: 224 backend tests / 52 subtests and 12 frontend tests passed.
  Initial frontend attempts exposed pre-existing sliced-picker fixtures missing
  the hidden-model constant and an outdated cache-version assertion; test-only
  corrections resolved them. No checkpoint load/render was attempted during any
  regression run. User registry SHA256 before/after remained
  `288df2ad42cfe82310fd6c4011cf7681a1ec68802633aa0b7df1036eedd41404`.
