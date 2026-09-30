# Wan 2.2 TI2V 5B MLX benchmark backend

This backend is experimental and does not replace the existing LTX video default.
Its purpose is to measure whether a materially smaller video transformer is a
better fit for a 48 GB Apple Silicon machine.

## Pinned components

- Runtime: `Blaizzy/mlx-video` at commit
  `87db56a51758fefb748a359b90a5283bb8ba4837`.
- Runtime license: MIT.
- Model: `Anes1032/Wan2.2-TI2V-5B-mlx-q8` at revision
  `9624723c94ddf509832555c45e223a035baa7d1c`.
- Model lineage: converted/quantized derivative of
  `Wan-AI/Wan2.2-TI2V-5B`.
- Model/base-model license: Apache-2.0. The downloaded model repository also
  carries its `LICENSE` and `NOTICE` files.
- Tokenizer: `google/umt5-xxl`, Apache-2.0. Setup caches only tokenizer/config
  files; the Wan model already carries its own MLX UMT5 encoder weights.

All model tensor files used by this backend are Safetensors. The setup script
uses a dedicated virtual environment and never installs Wan dependencies into
Nobby's existing MLX/image runtimes.

## Install

```sh
bash scripts/setup-wan22-video-mlx
./scripts/restart-all.sh
```

The download is roughly 20 GB. The current experimental profile is:

| Nobby quality | Resolution | Diffusion steps | Scheduler | Guidance |
| --- | --- | ---: | --- | ---: |
| Fast | 1280×704 | 10 | UniPC | 5.0 |
| Standard | 1280×704 | 20 | UniPC | 5.0 |
| Quality | 1280×704 | 40 | UniPC | 5.0 |

Wan Preview is deliberately disabled until a native low-resolution profile has
been benchmarked. Wan output is 24 fps and does not generate audio.

## Benchmark against LTX 2.5 MLX Q4

Use Standard for the first apples-to-apples 720p comparison:

```sh
python3 scripts/benchmark-ltx-video.py \
  --models ltx-2.5-mlx-q4 wan2.2-ti2v-5b-mlx-q8 \
  --quality standard \
  --duration 5 \
  --fps 24 \
  --repeats 1
```

This keeps the prompt, seed, 1280×704 geometry, 5-second duration and 24 fps
constant. The diffusion algorithms and step counts are model-specific, so the
benchmark compares practical Nobby profiles rather than pretending the raw step
counts are equivalent.

For the speed-oriented Wan profile:

```sh
python3 scripts/benchmark-ltx-video.py \
  --models wan2.2-ti2v-5b-mlx-q8 \
  --quality fast \
  --duration 5 \
  --fps 24
```
