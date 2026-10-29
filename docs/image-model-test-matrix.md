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
