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

## 2026-11-06 — native Ultra+ integration (CPU/browser only)

Exact checkpoint: Juggernaut XL Ragnarok, Civitai model version `1759168`,
`juggernautXL_ragnarok.safetensors`, SHA256
`dd08fa32f98d05a2443ca1419e46df1575a0811f6e3b246d9dd47ff20f5eb66a`.
Architecture: SDXL; provider: existing `sdxl` / Diffusers MPS worker.
Installation: unchanged, not inspected or downloaded this run; the historical
2026-10-27 installed/rendered record above remains separate evidence.

Ultra+ integration status: **configured**. GPU/model load: **not attempted**;
real render time, peak RAM, swap and observed image quality: **not measured**.
No inference ran on the production Mac. Synthetic PNGs verify API/provider
canvases and artifact metadata, not model quality or GPU stability.

Settings: 40 steps, CFG 4.0, DPM++ 2M SDE Karras; resolution tests use seed 42,
metadata replay lets the service select a fresh seed. Exact supported canvases:
1248×1664, 1664×1248, 1664×1664, 1792×1008, 1008×1792, 1248×1824.
Existing Ultra remains 1536 long edge, including 1152×1536 for 3:4.

Test attempts and regressions: the initial 265-case CPU contract/runtime run
passed; the expanded combined run had 355 passes and two middleware-import
ordering failures after a shared FastAPI app had started. Final isolated groups
pass 349 core cases plus 67 subtests, 8 served-middleware cases and 26
additional img2img/region safety cases. The image
JS group initially exposed an obsolete Ultra-hidden assertion and a synthetic
CFG text-format assertion; final expanded group passes 44 cases after contract/fixture updates.
Browser startup initially hit macOS sandbox permissions; the authorized
isolated Chromium run then exposed a blur-transition timing assertion, now
waiting for the final computed style. Final 6 browser cases pass. None of
these attempts loaded a checkpoint or produced a real model image.

Known issues: real MPS memory/performance/quality and successful production
chat restore are unverified for Ultra+. Exact wide and Ragnarok ratios need
larger relative pixel increments than 3:4. Ultra+ editing/reference generation
is deliberately rejected; their existing smaller working canvases are retained.
Decision: **retain configured opt-in for review; retest on GPU only after
explicit approval**, keep Ultra as the selectable fallback. Do not promote
Ultra+ to `tested` from CPU/browser results.

Evidence: [implementation, exact dimensions, test commands, estimates and safe
manual acceptance](ultra-plus.md), [Chromium layout acceptance](image-card-layout.md),
`tests/test_ultra_plus.py`, `tests/e2e/test_image_card_layout.py`.

## 2026-11-06 — Follow-up: Ultra retained, Ultra+ deferred

Actual local Juggernaut XL / SDXL **Ultra** jobs completed at 1152×1536,
40 steps, with and without automatic chat-model release. Attempts associated
with the larger experimental profile triggered the active swap-growth
protection; one observed failure reported +2.03 GB. The failed-job display
does not itself prove what the requested quality/dimensions were, and no
successful ultra_plus job at 1248×1664 was verified.

**Decision:** Ultra is the highest regular chat quality. Ultra+ is hidden
in the generation UI, stale quality preferences are normalized to Ultra,
and the bounded experimental native API/implementation remains available
for future isolated validation. RAM limits, abort thresholds and automatic
model coordination remain unchanged. [Policy and limits](ultra-plus.md).
