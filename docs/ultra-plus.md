# Optional native Juggernaut XL Ultra+

`ultra_plus` is an explicit text-to-image quality for the existing
`juggernaut-xl` registry ID with provider `sdxl`. Factory Fast, Standard,
Quality and Ultra profiles are unchanged. Both Ultra and Ultra+ use 40 steps,
CFG 4.0 and the existing DPM++ 2M SDE Karras scheduler. Explicit expert sampling
values still override the preset. Ultra is available again in the Juggernaut
picker: the old UI restriction incorrectly assumed a 1216 px worker limit.

## Native canvases

Only these exact aspect ratios and canvases are accepted for Ultra+.
Equivalent aspect inputs resolve to the same canvas with `auto_size: true`.
With `auto_size: false`, the dimensions must exactly match one listed canvas.
Every dimension is divisible by 16; no resize/upscale stage is introduced.

| Format | Ultra+ pixels | Existing Ultra canvas | Pixel increase |
| --- | --- | --- | --- |
| 3:4 portrait | 1248 × 1664 | 1152 × 1536 | 17.36% |
| 4:3 landscape | 1664 × 1248 | 1536 × 1152 | 17.36% |
| Square | 1664 × 1664 | 1536 × 1536 | 17.36% |
| 16:9 landscape | 1792 × 1008 | 1536 × 864 | 36.11% |
| 9:16 portrait | 1008 × 1792 | 864 × 1536 | 36.11% |
| Ragnarok 13:19 portrait | 1248 × 1824 | 1056 × 1536 (rounded ratio) | 40.34% |

The larger increments for 16:9 and 13:19 preserve the exact ratio and /16
alignment. Their absolute pixel counts (1.806 MP and 2.276 MP) remain below
the square cap, 2.769 MP. The 3:4 reference is 2.077 MP. Unsupported ratios,
models/providers and arbitrary large canvases fail before provider execution.

The Pydantic generation envelope now accepts at most 1824 per edge so canonical
results can be replayed. The model-aware resolver still enforces the previous
1216 SDXL / 1024 other-model explicit bounds for ordinary requests. Existing
Ultra can replay up to its already-generated 1536 edge. Ultra+ additionally
requires the exact approved model/provider and finite canvas list. This is
not a general large-resolution switch. Other model profiles are unchanged.

The provider passes width/height straight into native SDXL inference. Its
existing output validation rejects a PNG with the wrong dimensions. Result
and chat artifact metadata preserve actual dimensions, quality and sampling;
the Plus quality profile records its exact-aspect policy and pixel cap.
Regenerate retains quality and canvas with `auto_size: false` and omits the
seed. Variants keep their canonical server-side parameters.

## Editing and references

Ultra+ applies to new text-to-image generation only. Existing Qwen editing,
region editing and reference-generation paths retain their smaller working
canvases. The edit request rejects `ultra_plus`; the modal hides it outside
explicit Juggernaut text-to-image selection. This avoids falsely labelling a
bounded img2img/reference render as native Ultra+. An Ultra+ result remains a
valid source for those existing edit/reference paths; the original source
file and download are untouched. SDXL img2img still makes a temporary copy
at its existing 1024 edge. Editing an Ultra+ source does not promise Ultra+
output dimensions. Original-vs-edit comparison remains available.

## Memory and performance: estimates, not measured stability

For 3:4, latent spatial positions and pixel-linear activations grow 17.36%.
Dense attention intermediates, where present, can grow about 37.74% with the
square of that count. These are component scaling estimates, not a total-RAM
or wall-time prediction: weights are unchanged, attention kernels, offloading,
VAE decode and allocator peaks determine actual usage. The wide and Ragnarok
formats have larger relative increments shown above. The new maximum canvas
has 17.36% more pixels than the existing maximum Ultra square.

No GPU load, MPS render, peak RAM, swap delta, visual quality or restore latency
has been measured for Ultra+ on the 48 GB M5 Max. It remains `configured`,
not GPU-tested. Existing leases, hard watermark, model/chat reserves,
sequential unload/restore and watchdogs are unchanged. Existing MPS OOM
sanitization remains in place; CPU MemoryError now also names insufficient
memory and suggests choosing Ultra or a smaller canvas. There is no retry or
quality fallback. Square Ultra+ is the highest absolute pixel/RAM exposure.

## Automated verification, 2026-11-06

CPU tests use synthetic provider PNGs and temporary homes/data. Browser tests
use an isolated web process or offline fixtures. No heavy model loads occur.

- 349 targeted Python cases and 67 subtests pass: native resolution/profile,
  model validation, complete image runtime, pipeline V2, variants, reference,
  edit reroll, SDXL memory safety, runtime budget/coordinator, early preview,
  option validation, existing Juggernaut/creator policy.
- 8 served-regeneration middleware tests pass in a separate fresh process.
- 26 additional img2img and region-edit safety/handoff cases pass.
- 44 Node tests pass across image modules, Ragnarok, region editing and privacy, including
  actual quality-modal selection/payload, preferences and native regeneration.
- 6 Chromium cases pass: four offline responsive/interaction cases and the
  existing full-chat image preview/download test at both fixture viewports.
- Diff whitespace, JavaScript/Python syntax, paired DE/EN translation audit
  and public privacy scan pass before push. Local synthetic screenshots: see [layout acceptance](image-card-layout.md).

Commands (use the existing test Python environment):

```sh
python -m pytest -q tests/test_ultra_plus.py tests/test_image_runtime.py \
  tests/test_image_variants.py tests/test_image_pipeline_v2.py \
  tests/test_image_reference.py tests/test_image_edit_reroll.py \
  tests/test_sdxl_memory_safety.py tests/test_runtime_budget.py \
  tests/test_runtime_coordinator.py tests/test_sdxl_early_artifact.py \
  tests/test_image_option_validation.py tests/test_juggernaut_quality_policy.py \
  tests/test_ragnarok_creator_presets.py
python -m pytest -q tests/test_image_regenerate_card_ui.py
python -m pytest -q tests/test_juggernaut_img2img.py tests/test_region_mask_editor.py \
  tests/test_region_memory.py tests/test_region_chat_handoff.py tests/test_region_ux_polish.py
node --test tests/test_image*.mjs tests/test_ragnarok*.mjs tests/test_media_privacy_ui.mjs \
  tests/test_juggernaut_img2img_ui.mjs tests/test_region_mask_editor.mjs tests/test_region_ux_polish.mjs
python -m pytest -q --e2e tests/e2e/test_image_card_layout.py \
  tests/e2e/test_acceptance.py::test_image_job_preview_download
```

Initial combined ordering placed the served-middleware suite after an already
started shared FastAPI app: two tests failed during middleware registration.
Both pass in a fresh process (8/8); the 349-case core group passes separately.
An old static JS assertion expected Ultra to be hidden for Juggernaut; it was
updated to the new model-bound Ultra+ visibility contract. A new modal fixture
assertion initially expected CFG text `4.0` instead of equivalent `4`; it now
compares the numeric value. No failed attempt involved real inference.

## Manual acceptance — only after explicit approval

Do not run generation, restart services or deploy as part of this PR.
After a separately approved rollout, use a disposable chat and a synthetic,
non-private prompt. Use the same seed, sampler, steps and CFG for comparison.

1. Record idle memory pressure and swap (`memory_pressure`,
   `sysctl vm.swapusage`); capture process RAM with Activity Monitor.
2. Generate one 3:4 Ultra image (1152 × 1536, 40 steps, CFG 4, fixed seed).
   Record native job time, peak RAM/pressure, swap before/after and chat restore.
3. Once the image worker is unloaded and chat restore completes, record the
   new idle baseline. Explicitly select Juggernaut Ultra+ and generate once
   with the same prompt/seed. Expect 1248 × 1664, 40 steps, CFG 4.
4. Stop the trial if the memory guard/OOM fires; retain Ultra. Do not retry
   automatically or change the watermark, reserves, swap policy or quality.
5. Download both originals; verify dimensions with
   `sips -g pixelWidth -g pixelHeight /path/to/download.png` (or `.webp`).
   Check preview/keyboard, region/edit/compare, Info, blur and narrower sidebar.
6. Reload the disposable chat; verify native quality, resolution, original
   download and restored actions. Record output identity, real timings,
   memory/swap, quality observations and retain/retest/reject in
   [the model matrix](image-model-test-matrix.md). Approve other formats
   separately, especially the larger square canvas.

## Review checkout and rollback (commands only; not executed)

Use an isolated checkout for review; it does not deploy or restart anything:

```sh
git fetch origin feature/image-card-ultra-plus
git worktree add ../mlx-nobby-image-review origin/feature/image-card-ultra-plus
```

After an explicitly approved merge, the code rollout command in a clean,
authorized deployment checkout is `git pull --ff-only origin main`. Follow the
existing deployment procedure only with separate approval. No restart command
is required or authorized by this PR.

Immediate usage fallback: select Ultra in the quality modal. For a code
rollback after merge, create a new branch and revert both feature commits in
reverse order, then review/push a separate rollback PR; never reset production
or force-push main. Exact commit hashes are in the PR and `git log`.

```sh
git switch -c rollback/image-card-ultra-plus origin/main
git revert <ultra-plus-commit> <horizontal-card-commit>
# Review/test, then push this rollback branch and open its PR; no auto-merge.
```

## Runtime decision — 2026-11-06: Ultra+ hidden from regular chat

After the original CPU/browser-only integration, local SDXL Ultra jobs
completed at **1152 × 1536** (3:4, 40 steps) on a 48 GB Apple Silicon
machine. Experimental attempts at the larger size encountered the active
swap-growth safeguard; one reported failure showed **+2.03 GB** of swap
during model execution. This does **not** establish an absolute 48 GB
hardware limit; it does establish that Ultra+ is not sufficiently reliable
for normal chat selection in this configuration.

The regular chat image-quality modal now offers **Ultra** as its highest
level and always hides Ultra+, including when Juggernaut XL is selected.
Previously saved Ultra+ creation preferences and session quality fall back
to Ultra, and hidden quality controls cannot select it. Batch creation also
does not offer Ultra+. Existing artifact display, original downloads and
historical regeneration handling are preserved.

The finite-canvas native Ultra+ provider/API implementation and its CPU
contracts remain for explicit future development/testing; they are **not**
a production recommendation or a generally exposed UI feature. There is
no change to GPU memory guards, model unload/restore, RAM reserves,
model weights or image-enhancement tools. Real Ultra+ success and safe
automatic 27B/4B handoff have not been validated. Re-enable only after a
separate GPU test and review.
