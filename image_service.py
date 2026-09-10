"""Native, local FLUX image service. Images stay on disk, never in API payloads."""
import secrets
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ConfigDict
import image_registry as registry
from image_providers import availability, run_provider
from local_security import LocalRequestGuard

OUTPUT = Path.home() / ".config/mlx-web/images"
MODEL = "FLUX.1-schnell"
DIFFUSIONKIT_MODEL = "argmaxinc/mlx-FLUX.1-schnell-4bit-quantized"
_lock = threading.Lock()
_running = None


class Generate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    prompt: str = Field(min_length=3, max_length=2000)
    model: str = "auto"
    width: int = Field(default=512, ge=256, le=1024)
    height: int = Field(default=512, ge=256, le=1024)
    steps: int | None = Field(default=None, ge=1, le=50)
    guidance: float | None = Field(default=None, ge=0, le=10)
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)


@asynccontextmanager
async def lifespan(app):
    registry.load_registry()
    yield


app = FastAPI(title="MLX nobby Images", lifespan=lifespan)
app.add_middleware(LocalRequestGuard)


@contextmanager
def exclusive():
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, "Ein Image-Auftrag läuft bereits. Bitte dessen Abschluss abwarten.")
    try:
        yield
    finally:
        _lock.release()


def registry_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(404, "Unbekanntes Image-Modell") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def describe(model):
    available, reason = availability(model)
    return model | {"available": available, "availability_note": reason}


@app.get("/health")
def health():
    data = registry_call(registry.load_registry)
    model = registry_call(registry.get_model)
    return {
        "ok": True,
        "status": "busy" if _running else "ready",
        "models": [m["id"] for m in data["models"] if m["enabled"]],
        "loaded": bool(_running), "running_model": _running,
        "backend": model["provider"] + "-mlx",
        "runtime_model": model.get("repository"),
        "default_model": data["default_model"], "offline": True,
    }


@app.get("/models")
def models():
    data = registry_call(registry.load_registry)
    return data | {"models": [describe(model) for model in data["models"]], "running_model": _running, "offline": True}


@app.get("/models/{model_id}")
def model_detail(model_id: str):
    return describe(registry_call(registry.get_model, model_id, require_enabled=False))


@app.post("/models")
def add_model(request: dict):
    with exclusive():
        return describe(registry_call(registry.add_model, request))


@app.put("/models/{model_id}")
def update_model(model_id: str, request: dict):
    with exclusive():
        return describe(registry_call(registry.update_model, model_id, request))


@app.post("/models/{model_id}/activate")
def activate(model_id: str):
    with exclusive():
        model = registry_call(registry.get_model, model_id)
        ready, reason = availability(model)
        if not ready:
            raise HTTPException(409, reason)
        registry_call(registry.set_default, model_id)
        return {"ok": True, "default_model": model_id, "loaded": False}


@app.post("/unload")
def unload():
    with exclusive():
        return {"ok": True, "loaded": False, "detail": "Image-Modelle werden nach jedem Auftrag freigegeben"}


@app.post("/generate")
def generate(request: Generate):
    global _running
    if request.width % 16 or request.height % 16:
        raise HTTPException(422, "width and height must be divisible by 16")
    with exclusive():
        model = registry_call(registry.get_model, request.model)
        params = request.model_dump()
        params["steps"] = request.steps if request.steps is not None else model["default_steps"]
        params["guidance"] = request.guidance if request.guidance is not None else model["default_guidance"]
        params["seed"] = request.seed if request.seed is not None else secrets.randbelow(2**31 - 1)
        if model["provider"] == "diffusionkit" and params["steps"] > 8:
            raise HTTPException(422, "FLUX.1-schnell/DiffusionKit unterstützt maximal 8 Steps")
        if model["model_family"] == "flux2-klein" and "base" not in model["base_model"] and params["guidance"] != 1:
            raise HTTPException(422, "FLUX.2 Klein distilled benötigt Guidance 1")
        if model["model_family"] == "z-image-turbo" and params["guidance"] != 0:
            raise HTTPException(422, "Z-Image Turbo unterstützt keine CFG-Guidance; 0 verwenden")
        OUTPUT.mkdir(parents=True, exist_ok=True)
        image_id = f"{int(time.time())}-{secrets.token_hex(6)}"
        path = OUTPUT / f"{image_id}.png"
        _running = model["id"]
        try:
            run_provider(model, params, path)
        except Exception as exc:
            detail = str(exc) if isinstance(exc, RuntimeError) else "Image-Provider konnte kein gültiges PNG erzeugen"
            raise HTTPException(503, detail) from exc
        finally:
            _running = None
        return {
            "id": image_id,
            "path": str(path),
            "mime_type": "image/png",
            "width": request.width,
            "height": request.height,
            "prompt": request.prompt,
            "model": model["id"],
            "provider": model["provider"],
            "model_family": model["model_family"],
            "quantization": model["quantization"],
            "loras": [l for l in model["loras"] if l["enabled"]],
            "guidance": params["guidance"],
            "seed": params["seed"],
            "steps": params["steps"],
            "created_at": time.time(),
        }
