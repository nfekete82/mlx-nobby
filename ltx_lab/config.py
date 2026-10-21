"""Version-pinned, offline lab configuration; no MLX imports."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
LAB = PROJECT / ".ltx-lab"
PRODUCTION = Path.home() / ".local/share/mlx-nobby/ltx-2-mlx"
MODEL = Path.home() / ".local/share/mlx-nobby/models/ltx-2.5-mlx-q4"
COMMITS = {
    "0.16.3": "ae3b7ea9583db775bd4a1dfb506fb789585021e7",
    "0.17.0": "62b7651406f8ad4a0b7a3f36a93874a1015d59ca",
}
PROFILES = {
    # Keep the production compute path as a separate control: Q4 != BF16 compute.
    "production-control": {"dtype": "float32", "sparse": False},
    "bf16-baseline": {"dtype": "bfloat16", "sparse": False},
    "fp16": {"dtype": "float16", "sparse": False},
    "sparse": {"dtype": "bfloat16", "sparse": True},
    "fp16-sparse": {"dtype": "float16", "sparse": True},
}
DEFAULT_PROMPT = (
    "Cinematic tracking shot of a red sports car driving through rain at night, "
    "realistic reflections, smooth motion"
)


def runtime_path(version):
    return LAB / f"runtime-v{version}"


def inside_lab(path):
    value = Path(path).expanduser().resolve()
    if not value.is_relative_to(LAB.resolve()) or value == LAB.resolve():
        raise ValueError(f"Test outputs/runtime must be below {LAB}")
    return value


def experiment_environment(profile, cache_root):
    """Remove inherited experiment knobs, then set only recorded test options."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("LTX2_", "LTX_MLX_", "MLX_VIDEO_"))
           and k not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
    cache = inside_lab(cache_root)
    env.update({
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "HF_HOME": str(cache / "hf"), "HF_HUB_CACHE": str(cache / "hf/hub"),
        "XDG_CACHE_HOME": str(cache), "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1", "TOKENIZERS_PARALLELISM": "false",
        "LTX2_COMPUTE_DTYPE": PROFILES[profile]["dtype"],
        "LTX2_SOL_TAU": "1.0,1.25,1.5" if PROFILES[profile]["sparse"] else "off",
    })
    return env
