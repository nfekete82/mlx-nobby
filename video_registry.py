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
MLX_MODEL_ROOT = Path(os.environ.get(
    "LTX_MLX_MODEL_ROOT",
    str(Path.home() / ".local/share/mlx-nobby/models"),
)).expanduser()
LTX_ID = "ltx-2.5-22b-distilled"
LTX_MLX_Q4_ID = "ltx-2.5-mlx-q4"
DEFAULT_MODEL_ID = LTX_MLX_Q4_ID
LTX_REPOSITORY = "Lightricks/LTX-2.5"
LTX_MLX_Q4_REPOSITORY = "dgrauet/ltx-2.5-mlx-q4"
REVISION = 4
_lock = threading.RLock()

REQUIRED_FILES = (
    "ltx-2.5/ltx-2.5-22b-distilled-transformer-bf16.safetensors",
    "ltx-2.5/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
    "ltx-2.5/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
    "ltx-2.5/ltx-2.5-video-vae-conv-bf16.safetensors",
    "ltx-2.5/ltx-2.5-audio-vae-bf16.safetensors",
)
MLX_READY_MARKER = ".mlx-nobby-ready"


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
        "experimental": False,
    }


def builtin_mlx_model():
    return {
        "id": LTX_MLX_Q4_ID,
        "display_name": "LTX 2.5 MLX Q4 (local)",
        "provider": "ltx-mlx",
        "repository": LTX_MLX_Q4_REPOSITORY,
        "model_family": "ltx-2.5",
        "quantization": "int4",
        "capabilities": ["t2v", "i2v", "audio", "native-mlx"],
        "pipeline": "distilled-two-stage",
        "default_resolution": "720p",
        "default_duration": 5,
        "default_fps": 24,
        "inference_steps": 11,
        "enabled": True,
        "experimental": False,
    }


def _builtin_models():
    return [builtin_model(), builtin_mlx_model()]


def model_path(model):
    if str(model.get("provider") or "") == "ltx-mlx":
        return MLX_MODEL_ROOT / LTX_MLX_Q4_ID
    return MODEL_ROOT / "ltx-2.5"


def local_files_available(model):
    if str(model.get("provider") or "") == "ltx-mlx":
        root = model_path(model)
        return (
            (root / MLX_READY_MARKER).is_file()
            and (root / "embedded_config.json").is_file()
        )
    return all((MODEL_ROOT / relative).is_file() for relative in REQUIRED_FILES)


def missing_files(model):
    if str(model.get("provider") or "") == "ltx-mlx":
        root = model_path(model)
        required = (MLX_READY_MARKER, "embedded_config.json")
        return [name for name in required if not (root / name).is_file()]
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
        models = _builtin_models()
        stored = {}
        if REGISTRY_FILE.is_file():
            try:
                stored = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                stored = {}

        existing_by_id = {
            item.get("id"): item
            for item in stored.get("models", [])
            if isinstance(item, dict) and item.get("id")
        }
        for model in models:
            existing = existing_by_id.get(model["id"])
            if existing:
                model["enabled"] = bool(existing.get("enabled", True))

        available_ids = {model["id"] for model in models}
        env_default = os.environ.get("MLX_VIDEO_DEFAULT_MODEL")
        stored_default = stored.get("default_model")
        try:
            stored_revision = int(stored.get("revision") or 0)
        except (TypeError, ValueError):
            stored_revision = 0

        if env_default:
            requested_default = str(env_default)
        elif stored_revision < REVISION and stored_default == LTX_ID:
            # Revision 4 promotes the benchmarked native-MLX Q4 backend. Migrate
            # the former built-in MPS default once while preserving later user
            # selections and explicit environment overrides.
            requested_default = DEFAULT_MODEL_ID
        else:
            requested_default = str(stored_default or DEFAULT_MODEL_ID)

        default_model = (
            requested_default
            if requested_default in available_ids
            else DEFAULT_MODEL_ID
        )
        data = {
            "revision": REVISION,
            "default_model": default_model,
            "models": models,
        }

        if stored != data:
            _write(data)
        return data


def set_default_model(model_id):
    with _lock:
        data = load_registry()
        model = next((item for item in data["models"] if item["id"] == model_id), None)
        if model is None:
            raise KeyError(model_id)
        if not model["enabled"]:
            raise ValueError("Video-Modell ist deaktiviert")
        data["default_model"] = model_id
        _write(data)
        return model


def get_model(model_id="auto"):
    data = load_registry()
    target = data["default_model"] if model_id == "auto" else model_id
    model = next((item for item in data["models"] if item["id"] == target), None)
    if model is None:
        raise KeyError(target)
    if not model["enabled"]:
        raise ValueError("Video-Modell ist deaktiviert")
    return model
