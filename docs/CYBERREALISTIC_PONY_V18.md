# CyberRealistic Pony v18 local commissioning

Verified on **2026-10-27**, Apple M5 Max, 48 GB Unified Memory. Pony is installed
and enabled as an additional explicit choice; `juggernaut-xl` remains the
persistent default. Fresh installations still receive a disabled Pony built-in.

## Installation and provenance

- Registry ID: `cyberrealistic-pony-v18`, display name:
  **CyberRealistic Pony v18 CoreShift**.
- Architecture: Pony Diffusion V6 XL / SDXL; provider `sdxl`, native
  Diffusers/PyTorch **MPS**, FP16, no quantization. This is not MLX inference.
- Source: [author's Hugging Face repository](https://huggingface.co/cyberdelia/CyberRealisticPony),
  pinned revision `bf85880a58614199d0391c93151211be2832bb8c`.
- File: `CyberRealisticPony_V18.0_F16.safetensors`, **6,938,041,288 bytes**.
- Full SHA256:
  `1d580c1c3f3612fa4db88af65372255582d5509ca0b28f85387273368301941b`.
  The completed download was hashed before its `.part` file was published as a
  usable checkpoint. The [source file metadata](https://huggingface.co/cyberdelia/CyberRealisticPony/blob/bf85880a58614199d0391c93151211be2832bb8c/CyberRealisticPony_V18.0_F16.safetensors)
  reports the same hash. Download used `curl --continue-at -` with bounded retries.
- Installed at `~/Models/CyberRealisticPonyV18/`. No FP32 checkpoint, extra model,
  embedding or external VAE was downloaded. The checkpoint's VAE is used.
- Local `config/` was copied from the working `~/Models/JuggernautXL/config/`:
  JSON/text configuration and tokenizer assets only, excluding its cache and
  weights. All required component configs and both tokenizers were checked.
  Existing Juggernaut files were neither replaced nor edited.
- `~/Models/CyberRealisticPonyV18/installation.json` records source, checkpoint
  size/hash, verification time and SHA256 hashes of the copied configuration.

Only Pony's enabled flag was changed in the persistent registry. Comparing the
before/after state confirmed that all pre-existing model entries and the default
were preserved, including Juggernaut's user settings of **30 steps / CFG 5**.
Pony's requested standard defaults are **35 steps / CFG 5**.

## Sampler and Clip Skip

Pony generation now selects the already implemented `dpmpp-2m-sde-karras`
preset: `DPMSolverMultistepScheduler`, `algorithm_type=sde-dpmsolver++`,
`solver_order=2`, `use_karras_sigmas=True`. Juggernaut's selection is unchanged.
Fast / Standard / Quality profiles remain 20/35/35 steps, CFG 5/5/5.5 and long
edges 768/1216/1216.

The [creator's recommended settings](https://cyberrealistic.org/cyberrealistic-pony)
include UI Clip Skip 2. Installed Diffusers **0.40.0** supports `clip_skip` in both
SDXL text-to-image and img2img, but its semantics are **additional** skipping:
`clip_skip=None` selects `hidden_states[-2]`, while `clip_skip=2` selects `[-4]`.
The existing default already supplies the appropriate penultimate CLIP layer;
no extra skipping or backend rewrite was needed. This was checked directly in
the installed `StableDiffusionXLPipeline.encode_prompt` implementation.

Installed runtime: PyTorch **2.14.0**, Transformers **5.16.1**, Accelerate
**1.15.0**, MPS available. Existing CPU offload, VAE slicing/tiling, process
memory guard, 90% system-memory boundary and bounded MPS watermarks were retained.
No attention slicing, allocator-limit relaxation or safety bypass was added.

## Real production-API renders

The idle Image-Service was gracefully restarted before testing. A temporary
launch environment requested PNG output; the LaunchAgent plist was not edited.
After testing, a second graceful restart restored the existing output-format
policy (normally WebP). Both runs used `/jobs`, the existing exclusive media
runtime lease, chat handoff/restoration and SDXL process cleanup.

Identical request parameters: **832×1216, 35 steps, CFG 5, seed 27102026,
DPM++ 2M SDE Karras, standard quality, auto-size off**, default penultimate CLIP
layer. Each job started a fresh SDXL worker and unloaded it before chat restored.
No upscale or image editing was applied.

Positive prompt:

```text
score_9, score_8_up, score_7_up, rating_safe, photorealistic full-body photograph of a 35-year-old woman standing in a garden, fully clothed in a blue long-sleeved shirt, beige trousers and shoes, head and feet visible, natural daylight, realistic skin texture, relaxed pose.
```

Negative prompt:

```text
illustration, anime, cartoon, low quality, blurry, extra limbs, watermark, text
```

| Measurement | Pony v18.0 | Juggernaut XL Ragnarok |
| --- | ---: | ---: |
| Start, 2026-10-27 CET | 11:25:57 | 11:26:27 |
| Worker model preparation | 0.646 s | 0.814 s |
| Worker total, including model preparation and PNG save | 15.607 s | 16.378 s |
| Provider stage, including worker startup/import and output validation | 19.236 s | 19.459 s |
| Resource admission / handoff before execution | 1.346 s | 1.339 s |
| Worker unload | 0.098 s | 0.113 s |
| Runtime return, including chat restoration | 9.294 s | 8.972 s |
| Complete Image-Service job | **30.001 s** | **29.901 s** |
| Client wall time, with 2-second polling | 30.089 s | 30.083 s |

These are **one cold smoke render per model**, not repeated warm benchmarks.
Worker preparation uses cached filesystem data and is not import/startup time.
The ~0.77 s worker difference is insufficient to claim a reproducible speedup;
complete job latency is effectively equal. Agent, network and frontend latency
are not measured by the Image-Service timing.

Both images passed Pillow verification and full decoding: RGB PNG, exact
832×1216 canvas, nonblank pixel statistics. Actual result IDs/providers matched
the requested registry models; this was not an automatic-model fallback.

| Model | Local artifact (outside Git) | PNG SHA256 |
| --- | --- | --- |
| Pony v18.0 | `~/.config/mlx-web/images/1793096759-dbb3c94107bf.png` | `75d7a2f3d3c44a23956bb012f0b7fa708d4514236475b08a0a93d98f950c6715` |
| Juggernaut XL Ragnarok | `~/.config/mlx-web/images/1793096789-150b5ba346ac.png` | `5ad9d9e19237ea1659d897da0300b00f02763693709d8330cfcd3311fcda5d59` |

Visual inspection: both show a fully clothed adult, full body including shoes,
in natural garden daylight with photographic appearance. Pony renders an
apparently much older subject than the requested 35 years; Juggernaut follows
the requested apparent age more closely. One image does not establish general
anatomical accuracy or comparative quality. **Decision: retain Pony opt-in and
retest prompt/age fidelity; retain Juggernaut as default.**

No GPU load, rendering, PNG validation, cleanup or chat-restoration failure
occurred. Memory pressure snapshots stayed `normal`; these are not peak-memory
measurements. Existing swap was already ~11.01 GiB before the first render and
~11.73 GiB after the second; no claim of swap-free execution is made.
System used-memory estimates before/after were 30.24/31.20 GiB for Pony and
31.20/27.84 GiB for Juggernaut. No guard threshold was changed.

Raw job snapshots, timing reports, prompts, image statistics, memory snapshots
and registry backups are retained locally in:
`~/.config/mlx-web/benchmarks/cyberrealistic-pony-v18-20261027/`.
The primary evidence file is `gpu-results.json`; no generated image is committed.

## Targeted validation

**202 tests and 34 subtests passed** across `test_cyberrealistic_pony`,
`test_juggernaut_scheduler_benchmark`, `test_juggernaut_quality_policy`,
`test_juggernaut_img2img`, `test_sdxl_memory_safety`, `test_sdxl_vae_diagnostic`,
`test_lustify_retirement`, `test_image_runtime`, `test_sdxl_early_artifact` and
`test_juggernaut_ragnarok_setup` using `test-venv/bin/python -m pytest -q`.
The only warning was the existing Starlette/httpx deprecation.
`git diff --check` passed. Final `/health` reported ready, no active job, no loaded
SDXL worker and Juggernaut as default; Pony reported enabled and available.
Persistent reproduction records confirmed each run's actual resolved model,
seed, dimensions, steps, CFG and scheduler. The original Juggernaut checkpoint
still matched its expected SHA256
`dd08fa32f98d05a2443ca1419e46df1575a0811f6e3b246d9dd47ff20f5eb66a`.

## Rollback and maintenance

To remove Pony from selectable models while retaining its installed weights,
wait until the Image-Service is idle, then:

```bash
curl --fail --silent --show-error -X PUT \
  -H 'Content-Type: application/json' -d '{"enabled":false}' \
  http://127.0.0.1:8030/models/cyberrealistic-pony-v18
```

This leaves Juggernaut and all other settings intact. `registry-before.json`
provides the exact pre-activation state for manual recovery; do not restore it
over later user changes. No dependency upgrade, checkpoint replacement or
LaunchAgent configuration change needs reversing. A Git revert of the related
commit can remove the integration independently of the local weights.

Update the [test matrix](image-model-test-matrix.md) after every subsequent test,
including failed attempts. Installation, loading or CPU tests alone never
qualify a model as `tested` (see the repository rule in `../AGENTS.md`).
