# Model & Image Intelligence — implementation and validation

Validation date: 2026-10-13. Branch: `feat/model-image-intelligence`.
Based on the three MFLUX preparation commits from PR #203; no production model
preferences are changed by this integration. The pull request is stacked on
`feat/mflux-022-model-upgrade` so those preparation changes are not duplicated
in its diff. Retarget to `main` after #203 is merged.

## Implemented image workflow

- One to ten ordered references through existing file selection, composer drop
  and clipboard handling. Numbered thumbnails, removal, drag reordering and
  Alt+Left/Right keyboard reordering work in the existing responsive composer.
- Chat action payloads carry ordered `file_context.references` entries containing
  uploaded `stored_path` and `file_id`. Single-reference clients remain compatible.
  The service also accepts `source_paths` directly and validates 1–10 entries.
- Natural composition commands such as “Setze Person 1 und Person 2 gemeinsam
  auf eine Parkbank” route to editing; analysis questions and video commands
  retain their established routes.
- The new disabled-by-default `mflux-qwen-image-2.1-edit` registry entry calls
  `mflux-generate-qwen-2.1-edit --image-paths ...`. Modern controls and more than
  three references select a locally available enabled Qwen 2.1 Edit automatically.
  Explicit edit model choices are retained; unsupported options fail explicitly.
- Dedicated expert controls expose edit model, seed, steps, guidance, strength,
  negative prompt, mask upload, object-based auto-mask, KV cache, step cache,
  optional prompt enhancement and optional result verification. Uploads finish
  before submission. Existing Fast/Standard/Quality selection remains in place.
  New labels are translated into German and English. LoRAs use existing registry
  controls and offline local resolution.
- Qwen 2.1 Edit profiles: Fast 10 steps/512 px, Standard 20/768, Quality 40/1024;
  guidance defaults to 1. Negative prompts require explicit guidance >1.
  Step cache requires KV cache. No FP16 compute switch is enabled.
- Source files must resolve inside existing managed media/upload roots, use
  PNG/JPEG/WebP and pass both PIL verification and decoding. Limits are 20 MiB
  and 25 million pixels per image. Corruption, disguised formats, oversized images
  and symlinks resolving outside the roots fail before inference.
- New multi-reference and Qwen 2.1 inputs use bounded working PNG copies with
  private permissions and EXIF orientation normalization. Masks must match the
  first reference's dimensions. Working inputs and masks are removed after success,
  provider failure, cancellation or callback failure. Uploaded originals retain
  the existing upload retention policy; they are not deleted as temporary inputs.
- Original reference lists are retained in private reproduction records, rather
  than temporary paths. Iterative reference editing and restored variant jobs can
  recover those lists. Public reference results omit the source path list.
- Results use the existing managed image directory, artifact IDs, media library,
  save/download/delete actions, job progress, cancellation and provider recovery.
  The existing “edit generated image” flow continues to bind the chosen artifact.

The Qwen CLI performs auto-mask, enhancement and verification with its built-in
vision encoder. These are explicit opt-ins and may add substantial inference
work. The application does not interpret the CLI's free-form verification text
as an identity guarantee. Its progress remains coarse unless the installed CLI
advertises structured events. Face, clothing and identity preservation remain
best effort; no local identity-quality claim has been established.

## Routing and model evaluation

Existing distinct media, vision, agent, coding, STT and TTS boundaries are retained.
Ordinary chat can opt into lightweight deterministic role selection using
`auto_route: true` on `/api/runtime/chat` or `/api/runtime/chat/stream`. Code requests
use the configured coding role, proof requests the configured agent role, and
simple requests stay on chat. A manually configured chat model always wins.
Multimodal content stays with the existing vision router. Unavailable or incomplete
local models fall back to chat. No discovery scores silently change model defaults.
The current installation's manual chat role therefore continues to win.

The existing Model Scout A/B API accepts `suite: "coding"`; its default remains
`"quick"`. Coding candidates in Scout's existing benchmark buttons request the
coding suite. It covers PHP, JavaScript, Python, comprehension, refactoring,
bugfixing, structured tool requests, workflow planning, JSON compliance and
unsupported claims. Scoring requires the requested JSON envelope; additional
prose or Markdown fences count as noncompliance. It never executes generated code.
This is a versioned deterministic micro-suite, not a real repository-agent or
function-calling benchmark. Full executable coding and agent-workflow evaluations
remain outside the measured results in this report.

Benchmarks share the global heavy-runtime lease and runtime lock, check local
weight/tokenizer completeness, and restore the baseline even if candidate switching
partially fails. Tokens/sec uses token usage from the same streamed request being
timed; estimates are labeled when usage is absent. Handoff duration and sampled
RSS are reported separately. Unified/Metal peak allocation is explicitly unknown.
The CLI benchmark backs up config privately and can record `tested` decisions in
the existing Model Evaluation store only with `--record-evaluations`.

## Real local measurements

Command executed with already installed weights, no downloads:

```sh
agent-venv/bin/python scripts/benchmark-coding.py \
  --aliases qwen38_20260927 qwen3-coder-30b devstral --runs 1 \
  --output artifacts/model-image-intelligence/coding-real.json
```

| Model alias | Strict tasks passed | Stream TTFT | Generation tokens/sec | Handoff |
| --- | ---: | ---: | ---: | ---: |
| qwen38_20260927 | 8/10 | 146 ms | 30.2 | Already active |
| qwen3-coder-30b | 6/10 | 92 ms | 113.4 | 4.410 s |
| devstral | Not run | — | — | Rejected by RAM admission |

These are **real inference** results from one micro-suite pass per model. They
have no statistical confidence interval. The performance probe warms the same
prompt before streaming, so its effective prefill rate includes cache effects
and is not a cold prefill benchmark. Refactoring scoring normalizes whitespace;
all other JSON task values must match. Qwen3.8 missed Python aliasing and fenced
a tool request. Qwen3-Coder also produced invalid tool-request JSON and the wrong
workflow ordering. No production model was replaced based on these measurements.

RSS samples were 0.25 GiB for the initial listener process and 14.49 GiB after
the coding-model handoff. The initial listener's RSS is not representative of
all inference allocations, so these figures are **not a comparable model-memory
ranking**, and neither is a peak unified-memory measurement. Peak Metal memory,
cold weight-load time and image inference time were not measured.

Before Devstral, the unchanged global guard rejected the next load at a projected
100.5% memory use with its existing 18 GiB loading reserve. The benchmark stopped
and restored `qwen38_20260927` and the exact original config; the report records
`baseline_restored: true`. The live service subsequently reported the original
model healthy. No guard, lock, or admission threshold was relaxed.

A read-only Qwen 2.1 Edit preflight found **no compatible local weights** for
`Qwen/Qwen-Image-2.1`. Therefore a real image-edit inference test was skipped and
no image speed/quality/memory claims are made. The available MLX-Serve quantized
cache is a different loader contract and was not repurposed or modified.
See `artifacts/model-image-intelligence/image-preflight.json`.

## Ornith compatibility assessment

Read-only inspection of the [model card](https://huggingface.co/mlx-works/Ornith-1.5-35B-A3B-oQ4e-mtp)
and [configuration](https://huggingface.co/mlx-works/Ornith-1.5-35B-A3B-oQ4e-mtp/blob/main/config.json)
found `qwen3_5_moe`, mixed affine quantization with a four-bit base, and one MTP
layer. The publisher describes a text-only conversion and advises leaving
Lightning MTP disabled. Those are publisher statements, not local measurements.

The installed `runtime-venv` has mlx-lm 0.31.3 with a `qwen3_5_moe` adapter.
Its `qwen3_5.py` sanitizer drops MTP tensors; native MTP acceleration therefore
cannot be inferred from the presence of that adapter. Architecture recognition
alone does not prove the specific mixed-precision weight pack loads correctly.
Scout now understands `oQ4e` names and recognizes Ornith as a coding candidate.
No Ornith weights were downloaded, no loading test was possible, and no alias or
production default was added. Candidate status remains conditional on explicit
weight-download approval, an offline load test and the same measured benchmarks.
No publisher performance numbers are substituted for local results.

## Validation

- Final full isolated CPU suite: **2,664 passed**, **430 subtests passed**,
  one warning, 49.83 seconds.
- Final full JavaScript suite: **242 passed**.
- Focused browser suite: **16 passed, 30 deselected**, Chromium desktop and mobile,
  controlled inference transport. Covers new reference controls, ordinary chat,
  image generation/download, video progress/cancellation and variant galleries.
  Two broader sessions stalled in existing model-console or image-download cases
  and were terminated; the fresh focused suite above completed successfully.
- New backend coverage includes 1/2/10 references, order and original preservation,
  corruption, disguised file formats, pixel limits, path boundaries, callback/
  provider/cancellation cleanup, masks, incompatible flags, reproduction records,
  manual routing and local model completeness.
- Existing regression suites cover missing weights, RAM rejection, ordinary chat,
  video, media persistence/deletion and iterative single-reference editing.
- `git diff --check` and JavaScript syntax checks passed.

All CPU/browser image renders are mocked inference. The two coding runs above
are real inference. No real Qwen 2.1 Edit, ten-reference GPU-memory, image identity,
FP16 comparison or Ornith inference result is claimed.

## Installation, migration and final checks

```sh
cd ~/mlx-web
git switch feat/model-image-intelligence
bash scripts/setup-mflux-mlx
# Restart only when idle, using the existing service controls.
# Enable Qwen Image 2.1 Edit in Settings > Models > Image only after supplying
# compatible local weights; keep existing default and manual roles as desired.
test-venv/bin/python -m pytest tests -q
node --test tests/*.mjs
test-venv/bin/python -m pytest tests/e2e/test_multi_reference.py --e2e -q
```

The setup helper installs the pinned **software** package, not image weights.
Existing registries gain a disabled Qwen 2.1 Edit entry on their next normal read;
`image-models.json.previous` preserves the pre-write registry. User defaults,
enabled flags and LoRAs remain under existing migration rules. No production
registry/config was migrated while implementing or running isolated CPU tests.

For repeatable coding comparisons, use the CLI above with `--runs 3` when memory
admission permits. It accepts only installed models and writes private config
backups beside the report, ignored by Git. Use a separate output path to preserve
older measurements. It does not adopt a winner. No weight download is part of
the installation or final checks above.

## Changed files

- `agent/app.py`
- `agent/media_queue.py`
- `agent/model_scout_routes.py`
- `agent/coding_benchmark.py`
- `agent/intelligent_routing.py`
- `backend/media_intent.py`
- `image_service.py`
- `image_providers.py`
- `image_registry.py`
- `mflux_capabilities.py`
- `quality_profiles.py`
- `scripts/benchmark-coding.py`
- `frontend/assets/chat/attachments.js`
- `frontend/assets/chat/generation.js`
- `frontend/assets/chat.css`
- `frontend/assets/chat/model-scout.js`
- `frontend/assets/chat/model-scout-v3.js`
- `frontend/i18n/de.json`
- `frontend/i18n/en.json`
- `tests/test_multi_reference_edit.py`
- `tests/test_intelligence_benchmark.py`
- `tests/test_image_reference.py`
- `tests/test_image_option_contracts.mjs`
- `tests/test_image_edit.mjs`
- `tests/test_image_option_validation.py`
- `tests/test_mflux_capabilities.py`
- `tests/test_system_update_scripts.py`
- `tests/e2e/test_multi_reference.py`
- `.gitignore`
- `docs/MFLUX_COMPATIBILITY.md`
- `docs/MODEL_IMAGE_INTELLIGENCE.md`
- `artifacts/model-image-intelligence/coding-real.json`
- `artifacts/model-image-intelligence/image-preflight.json`


## Osaurus Qwen Image 2.1 Edit 4-bit (opt-in follow-up)

The separate built-in `mflux-osaurus-qwen-image-2.1-edit` points to
`OsaurusAI/Qwen-Image-2.1-mflux-4bit`. It is **disabled by default**,
never adopted as the global image default, and never downloaded by registry
discovery. The model was successfully loaded through standalone MFLUX 0.22.0
with a 512px/4-step image; that run reported 5.74 GB peak MLX memory.
A later real multi-reference CLI run was reported successful, but its
measurements were not captured as reproducible evidence here.

This checkpoint is already quantized. Its registry entry deliberately sets
`quantize_on_load=False`; the command uses cached snapshot files directly
and does not pass `--quantize 4`. The strict quantized-text-encoder safeguard
remains in force for other repositories; the one specific approved checkpoint
has an exception due to successful standalone MFLUX loading.

On the target Mac, after pulling this branch and while image services are idle:

```sh
cd ~/mlx-web
test-venv/bin/python -m pytest -q tests/test_mflux_capabilities.py tests/test_multi_reference_edit.py
# Restart the image service through the existing MLX Nobby management command.
# Then open Settings > Models > Image, select Osaurus Qwen 2.1 Edit, enable it.
# Keep all global defaults unchanged; select Osaurus explicitly in the composer.
```

Use two image attachments in the chat to verify real output. The integration
still uses the application's runtime lease, image queue, private input copies
and existing RAM admission rules. Compare the in-app real result with the
successful standalone CLI result before treating the workflow as production
validated. No memory or timing promises follow from a single 512px test.

Check the checkpoint's model-card license before commercial use.
