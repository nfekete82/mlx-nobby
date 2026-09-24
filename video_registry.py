"""Persistent registry for local video models (separate from image and LLM roles)."""
import json
import os
import tempfile
import threading
from pathlib import Path


REGISTRY_FILE = Path(os.environ.get(
    "MLX_VIDEO_REGISTRY",
    str(Path.home() / ".config/mlx-web/video-models.json"),
)).expanduser()
LTX_APP_DATA = Path(os.environ.get(
    "LTX_APP_DATA_DIR",
    str(Path.home() / "Library/Application Support/LTXDesktop"),
)).expanduser()
MODEL_ROOT = LTX_APP_DATA / "models"
LTX_ID = "ltx-2.5-22b-distilled"
LTX_REPOSITORY = "Lightricks/LTX-2.5"
REVISION = 2
_lock = threading.RLock()

REQUIRED_FILES = (
    "ltx-2.5/ltx-2.5-22b-distilled-transformer-bf16.safetensors",
    "ltx-2.5/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
    "ltx-2.5/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
    "ltx-2.5/ltx-2.5-video-vae-conv-bf16.safetensors",
    "ltx-2.5/ltx-2.5-audio-vae-bf16.safetensors",
)


def builtin_model():
    return {
        "id": LTX_ID,
        "display_name": "LTX 2.5 Fast (local)",
        "provider": "ltx-desktop-headless",
        "repository": LTX_REPOSITORY,
        "model_family": "ltx-2.5",
        "quantization": "bf16 streaming",
        "capabilities": ["t2v", "i2v", "audio"],
        "pipeline": "fast",
        "default_resolution": "720p",
        "default_duration": 5,
        "default_fps": 24,
        "inference_steps": 11,
        "enabled": True,
    }


def model_path(_model):
    return MODEL_ROOT / "ltx-2.5"


def local_files_available(_model):
    return all((MODEL_ROOT / relative).is_file() for relative in REQUIRED_FILES)


def missing_files(_model):
    return [relative for relative in REQUIRED_FILES if not (MODEL_ROOT / relative).is_file()]


def _write(data):
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".video-models-", suffix=".json", dir=REGISTRY_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, REGISTRY_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_registry():
    with _lock:
        model = builtin_model()
        if REGISTRY_FILE.is_file():
            try:
                stored = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
                existing = next(
                    (item for item in stored.get("models", []) if item.get("id") == LTX_ID),
                    None,
                )
                if existing:
                    model["enabled"] = bool(existing.get("enabled", True))
            except (OSError, ValueError, TypeError):
                pass
        data = {"revision": REVISION, "default_model": LTX_ID, "models": [model]}
        if not REGISTRY_FILE.is_file():
            _write(data)
        return data


def get_model(model_id="auto"):
    data = load_registry()
    target = data["default_model"] if model_id == "auto" else model_id
    model = next((item for item in data["models"] if item["id"] == target), None)
    if model is None:
        raise KeyError(target)
    if not model["enabled"]:
        raise ValueError("Video-Modell ist deaktiviert")
    return model
