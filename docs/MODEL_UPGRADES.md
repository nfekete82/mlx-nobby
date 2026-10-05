# Recommended local model upgrades

This guide keeps upgrades explicit: MLX nobby does not download large model
weights merely because a feature exists. Download a candidate first, benchmark
where appropriate, then opt in.

## Qwen3.8 speculative decoding (DFlash2)

Recommended pair:

- target: `mlx-community/Qwen3.8-27B-4bit`
- drafter: `z-lab/Qwen3.8-27B-DFlash2`

DFlash2 is a draft model, not a standalone chat model. The runtime only enables
it when the currently loaded model exactly matches the target that was active
when the configurator was enabled. Switching to a coding or other model therefore
disables the drafter automatically.

The upstream `mlx-community/Qwen3.8-27B-MTP-4bit` preset is intentionally not the
default here. A current mlx-vlm issue reports NaN/Inf weights and zero draft
acceptance for that 4-bit MTP checkpoint. Reconsider it only after that upstream
checkpoint or issue is confirmed fixed:

<https://github.com/Blaizzy/mlx-vlm/issues/1931>

Download DFlash2 explicitly:

```sh
./scripts/mlx download z-lab/Qwen3.8-27B-DFlash2
```

Then, while the desired Qwen3.8 target is the active runtime model:

```sh
bash scripts/configure-qwen38-speculative enable
./scripts/mlx restart
```

Inspect or disable it with:

```sh
bash scripts/configure-qwen38-speculative status
bash scripts/configure-qwen38-speculative disable
./scripts/mlx restart
```

The runtime accepts only a local path or an already cached Hugging Face drafter.
A missing drafter degrades to normal generation rather than downloading during
service startup. Invalid speculative-decoding settings fail fast. DFlash2 uses
its model-provided block size unless an explicit `SPECULATIVE_DRAFT_BLOCK_SIZE`
is configured.

## Dedicated coding role

MLX nobby already has a separate `coding` model role. A strong 48 GB-class
candidate is:

`mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit`

Register and download it explicitly:

```sh
./scripts/mlx model add qwen3-coder-30b mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit
./scripts/mlx download qwen3-coder-30b
```

Then assign `qwen3-coder-30b` to the **Coding** role in Settings → Models. The
normal Chat/Vision roles remain independent and can keep Qwen3.8.

## Whisper vs Qwen3-ASR

Production stays on Whisper until a local comparison says otherwise.
Recommended candidate:

`mlx-community/Qwen3-ASR-1.7B-6bit`

Download the candidate explicitly:

```sh
./scripts/mlx download mlx-community/Qwen3-ASR-1.7B-6bit
```

Prepare several representative recordings. For accuracy scoring, place a UTF-8
reference transcript next to each recording with the same stem, for example:

```text
samples/01.wav
samples/01.txt
samples/02.wav
samples/02.txt
```

Run the benchmark:

```sh
python3 scripts/benchmark-asr.py \
  --audio samples/01.wav \
  --audio samples/02.wav \
  --runs 2 \
  --output artifacts/asr-benchmark.json
```

Each model is benchmarked in a fresh speech-venv process, loaded once, and then
used for all samples. The report records load time, per-transcription timing,
and WER when reference sidecars exist. The recommendation prefers lower median
WER, then lower median inference time.

If Qwen3-ASR wins, persist it for the LaunchAgent and reload native services:

```sh
MLX_SPEECH_MODEL=mlx-community/Qwen3-ASR-1.7B-6bit ./scripts/install-launchd.sh
```

The installer preserves an existing `MLX_SPEECH_MODEL` value on later runs.
To return to Whisper, rerun the same command with:

```text
mlx-community/whisper-large-v3-turbo-asr-fp16
```

## What stays unchanged

These components do not need a model swap for this upgrade:

- Qwen Image 2.1 for image generation/editing
- LTX 2.5 for video
- Qwen3-Embedding-4B for retrieval
- the small Qwen3.5 router
- Qwen3-TTS 1.7B for current preset/custom and cloned voices

Treat future replacements the same way: discover, download explicitly, run a
local A/B test, and only then make the new candidate the production default.
