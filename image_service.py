"""Native, local image service. Images stay on disk, never in API payloads."""
import copy
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.request
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
import image_registry as registry
from image_job_timings import ImageJobTimings
from quality_profiles import dimensions_for_long_edge, resolve_image_profile
from image_edit_precision import infer_auto_mask_target, comparison_image_id, image_change_advisory
from image_region_edit import prepare_region, composite_region
import runtime_coordinator
import subprocess
from image_providers import (
    MLXSERVE_URL,
    PROCESS_TERMINATION_TIMEOUT,
    ProviderCancelled,
    availability,
    run_provider,
    sdxl_worker_running,
    shutdown_sdxl_worker,
    terminate_process_tree,
    realesrgan_command,
)
from local_security import LocalRequestGuard
from image_variants import install as install_image_variants

OUTPUT = Path.home() / ".config/mlx-web/images"
PROJECT_DIR = Path(__file__).resolve().parent
MLX_MANAGER = PROJECT_DIR / "scripts" / "mlx"
MLX_SERVER_LABEL = "de.nobby.mlx-server"
MODEL = "FLUX.1-schnell"
DIFFUSIONKIT_MODEL = "argmaxinc/mlx-FLUX.1-schnell-4bit-quantized"
_lock = threading.Lock()
_running = None
_jobs_lock = threading.RLock()
_jobs = {}
_active_job_id = None
_MAX_RETAINED_JOBS = 100


class Generate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    prompt: str = Field(min_length=3, max_length=2000)
    negative_prompt: str | None = Field(default=None, max_length=2000)
    model: str = "auto"
    width: int = Field(default=512, ge=256, le=1216)
    height: int = Field(default=512, ge=256, le=1216)
    steps: int | None = Field(default=None, ge=1, le=50)
    guidance: float | None = Field(default=None, ge=0, le=10)
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    quality: Literal["fast", "standard", "quality", "ultra"] | None = None
    auto_size: bool = False
    original_prompt: str | None = None
    # Diagnostic only. Defaults preserve the current safe SDXL VAE pipeline.
    sdxl_vae_mode: Literal["optimized", "disabled"] | None = None


class Edit(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    prompt: str = Field(min_length=3, max_length=2000)
    source_path: str | None = None
    source_paths: list[str] | None = Field(default=None, min_length=1, max_length=10)
    mask_path: str | None = None
    auto_mask: str | None = Field(default=None, min_length=1, max_length=200)
    precision_edit: bool = True  # Conservatively infer unambiguous Qwen auto-mask targets.
    region_edit: bool = False  # Opt-in cropped, composited, RAM-sparing brush edits.
    region_feather_px: int = Field(default=0, ge=0, le=12)  # Softens only inside the painted mask.
    strength: float | None = Field(default=None, gt=0, le=1)
    use_kv_cache: bool | None = None
    use_step_cache: bool | None = None
    step_cache_threshold: float | None = Field(default=None, gt=0, le=1)
    enhance_prompt: bool | None = None
    verify: bool | None = None
    model: str = "auto"
    steps: int | None = Field(default=None, ge=1, le=50)
    guidance: float | None = Field(default=None, ge=0, le=10)
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    quality: Literal["fast", "standard", "quality", "ultra"] | None = None

    semantic_operation: Literal['edit', 'reference_generate'] = 'edit'
    reference_mode: Literal['same_identity', 'resemblance'] | None = None
    reference_artifact_id: str | None = None
    original_prompt: str | None = None
    width: int | None = Field(default=None, ge=256, le=1216)
    height: int | None = Field(default=None, ge=256, le=1216)
    auto_size: bool = False
    negative_prompt: str | None = Field(default=None, max_length=2000)

    @model_validator(mode='after')
    def reference_contract(self):
        if not self.source_path and not self.source_paths:
            raise ValueError('At least one reference image is required')
        if self.source_paths:
            if self.source_path and self.source_path != self.source_paths[0]:
                raise ValueError('source_path must match the first reference')
            self.source_path = self.source_paths[0]
        if self.use_step_cache and self.use_kv_cache is False:
            raise ValueError('Step cache requires KV cache')
        if self.mask_path and self.auto_mask:
            raise ValueError('Choose a mask or auto-mask')
        if self.region_edit and (
            not self.mask_path or self.auto_mask or self.source_paths
            or self.semantic_operation != 'edit'
        ):
            raise ValueError('Region edit requires one source and a manual mask')
        if self.region_feather_px and not self.region_edit:
            raise ValueError('Mask feather requires region edit')
        if self.semantic_operation == 'reference_generate' and self.reference_mode is None:
            raise ValueError('Reference generation requires a reference mode')
        if (self.width is None) != (self.height is None):
            raise ValueError('Both target dimensions are required')
        return self


class Upscale(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str
    preset: Literal[
        "photo-2x",
        "photo-4x",
        "anime-4x",
    ] = "photo-2x"
    tile: int = Field(default=0, ge=0)


class ImageJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["generate", "edit", "upscale"]
    payload: dict
    chat_id: str = Field(min_length=1)
    run_id: str | None = None
    chat_revision: int = Field(
        ge=0,
        strict=True,
    )


@asynccontextmanager
async def lifespan(app):
    registry.load_registry()
    try:
        yield
    finally:
        with _jobs_lock:
            active = [
                _cancel_job(job)
                for job in _jobs.values()
                if job.get("status") in {"queued", "loading", "running", "saving"}
            ]
        for process, thread in active:
            if process is not None:
                terminate_process_tree(process)
            if thread is not None:
                thread.join(timeout=PROCESS_TERMINATION_TIMEOUT * 2 + 1)
        shutdown_sdxl_worker()


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
    result = model | {"available": available, "availability_note": reason}
    if model['provider'] == 'mflux':
        from image_providers import MFLUX_BIN, probe_mflux_cli
        capabilities = probe_mflux_cli(str(MFLUX_BIN / registry.FAMILIES[model['model_family']][0]))
        result['cli_capabilities'] = capabilities | {'supported_flags': sorted(capabilities['supported_flags'])}
    return result


def _chat_server_loaded():
    domain = f"gui/{os.getuid()}/{MLX_SERVER_LABEL}"
    result = subprocess.run(
        ["launchctl", "print", domain],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _chat_server_command(action):
    result = subprocess.run(
        ["/bin/bash", str(MLX_MANAGER), action],
        cwd=PROJECT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=120,
        check=False,
    )

    if result.returncode != 0:
        message = result.stdout.strip() or f"mlx {action} fehlgeschlagen"
        raise RuntimeError(message[-4000:])


def _unload_mlxserve_model(model):
    body = json.dumps({
        "model": model["repository"],
    }).encode("utf-8")

    request = urllib.request.Request(
        MLXSERVE_URL + "/v1/unload-model",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(
                f"MLX-Serve unload lieferte HTTP {response.status}"
            )


def _loaded_mlxserve_repository_ids(*, strict=False):
    """Return repository IDs that MLX-Serve reports as resident."""
    try:
        with urllib.request.urlopen(
            MLXSERVE_URL + "/v1/models",
            timeout=3,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        if strict:
            raise RuntimeError(
                "MLX-Serve-Modellstatus konnte nicht gelesen werden"
            ) from exc
        return []

    return [
        item.get("id")
        for item in payload.get("data", [])
        if (
            isinstance(item, dict)
            and item.get("loaded") is True
            and isinstance(item.get("id"), str)
        )
    ]


def _loaded_mlxserve_models():
    """Return configured image models that MLX-Serve reports as resident."""
    loaded_repositories = set(_loaded_mlxserve_repository_ids())
    if not loaded_repositories:
        return []

    repositories = {
        model.get("repository"): model
        for model in registry_call(registry.load_registry)["models"]
        if model.get("provider") == "mlxserve"
    }
    return [
        repositories[repository]
        for repository in loaded_repositories
        if repository in repositories
    ]


def _unload_mlxserve_model_and_wait(model):
    """Unload one resident MLX-Serve image model before chat is restored."""
    try:
        timeout = float(
            os.environ.get("MLX_IMAGE_MLXSERVE_UNLOAD_TIMEOUT", "15")
        )
    except (TypeError, ValueError):
        timeout = 15.0
    timeout = max(1.0, min(timeout, 60.0))

    repository = model.get("repository")
    if not isinstance(repository, str) or not repository:
        raise RuntimeError("MLX-Serve-Modell hat keine Repository-ID")

    def still_loaded():
        return repository in _loaded_mlxserve_repository_ids(strict=True)

    if not still_loaded():
        return

    _unload_mlxserve_model(model)
    deadline = time.monotonic() + timeout

    while still_loaded():
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "MLX-Serve hat das Image-Modell nicht rechtzeitig entladen"
            )
        time.sleep(0.25)


@app.get("/health")
def health():
    data = registry_call(registry.load_registry)
    model = registry_call(registry.get_model)
    sdxl_loaded = sdxl_worker_running()
    mlxserve_loaded = _loaded_mlxserve_models()
    loaded = bool(_running) or sdxl_loaded or bool(mlxserve_loaded)
    running_model = _running
    if running_model is None and sdxl_loaded:
        running_model = registry.JUGGERNAUT_XL_ID
    if running_model is None and mlxserve_loaded:
        running_model = mlxserve_loaded[0]["id"]

    with _jobs_lock:
        active_job = _jobs.get(_active_job_id)
        active_generation = bool(
            active_job
            and active_job.get("phase") != "waiting_for_resources"
        )

    return {
        "ok": True,
        "status": "busy" if _running or _active_job_id else "ready",
        "active_generation": active_generation,
        "active_job_id": _active_job_id,
        "models": [m["id"] for m in data["models"] if m["enabled"]],
        "loaded": loaded,
        "running_model": running_model,
        "sdxl_worker_loaded": sdxl_loaded,
        "backend": model["provider"] + "-mlx",
        "runtime_model": model.get("repository"),
        "default_model": data["default_model"], "offline": True,
    }


def validate_edit_source(value: str) -> Path:
    path = Path(value).expanduser().resolve()

    allowed_roots = (
        OUTPUT.resolve(),
        (
            Path.home()
            / ".config/mlx-web/uploads"
        ).resolve(),
        (
            Path.home()
            / ".config/mlx-web/attachments"
        ).resolve(),
        (
            Path.home()
            / ".config/mlx-web/batch/uploads"
        ).resolve(),
    )

    if not any(
        path.is_relative_to(root)
        for root in allowed_roots
    ):
        raise HTTPException(
            422,
            "Das Quellbild liegt außerhalb der erlaubten MLX-Nobby-Verzeichnisse",
        )

    if (
        not path.is_file()
        or path.suffix.lower() not in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
        }
    ):
        raise HTTPException(
            422,
            "Ungültiges Quellbild",
        )

    from PIL import Image, UnidentifiedImageError
    import warnings
    try:
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError('Image exceeds 20 MB')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format not in {'PNG', 'JPEG', 'WEBP'} or image.width * image.height > 25_000_000:
                    raise ValueError('Unsupported image or pixel budget')
                image.verify()
            with Image.open(path) as image:
                image.load()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, 'Beschädigtes, zu großes oder ungültiges Quellbild') from None
    return path


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
        try:
            shutdown_sdxl_worker()
            for model in _loaded_mlxserve_models():
                _unload_mlxserve_model(model)
        except RuntimeError as exc:
            raise HTTPException(
                500,
                "Image-Modell konnte nicht vollständig entladen werden",
            ) from exc

        return {
            "ok": True,
            "loaded": False,
            "sdxl_worker_loaded": sdxl_worker_running(),
            "detail": "Image-Modell wurde entladen",
        }


def _provider_failure(exc):
    return (
        str(exc)
        if isinstance(exc, RuntimeError)
        else "Image-Provider konnte kein gültiges PNG erzeugen"
    )


def _auto_generation_model(prompt):
    data = registry_call(registry.load_registry)
    value = str(prompt or "").lower()

    def candidate(model_id):
        model = next(
            (item for item in data["models"] if item["id"] == model_id),
            None,
        )
        if (
            not model
            or not model["enabled"]
            or "text_to_image" not in model.get("capabilities", [])
        ):
            return None
        ready, _ = availability(model)
        return model if ready else None

    text_image = re.search(
        r"\b(?:poster|typography|text|lettering|logo|ui|interface|schrift|typografie)\b",
        value,
    )
    realistic_style = re.search(
        r"\b(?:photorealistic|photo-realistic|realistic(?: photo)?|photograph|fotorealistisch|realistisch(?:es foto)?)\b",
        value,
    )
    human_subject = re.search(
        r"\b(?:portrait|porträt|person|people|human|menschen?|woman|man|frau|mann|fashion|modefoto)\b",
        value,
    )
    complex_prompt = re.search(
        r"\b(?:complex prompt|high prompt fidelity|komplexer prompt|hohe prompttreue)\b",
        value,
    )
    fast_request = re.search(
        r"\b(?:fast|quick|preview|draft|schnell|vorschau|entwurf)\b",
        value,
    )

    preferred_ids = []
    if fast_request:
        preferred_ids.append(registry.Z_IMAGE_TURBO_ID)
        preferred_ids.append(registry.MLXSERVE_QWEN_IMAGE21_ID)
    elif text_image:
        preferred_ids.append(registry.MLXSERVE_QWEN_IMAGE21_ID)
    elif realistic_style and human_subject:
        preferred_ids.append(registry.MLXSERVE_QWEN_IMAGE21_ID)
        preferred_ids.append(registry.JUGGERNAUT_XL_ID)
    elif complex_prompt:
        preferred_ids.append(registry.MLXSERVE_QWEN_IMAGE21_ID)

    for model_id in preferred_ids:
        model = candidate(model_id)
        if model:
            return model
    default_model = candidate(data["default_model"])
    if default_model:
        return default_model
    for model in data["models"]:
        fallback = candidate(model["id"])
        if fallback:
            return fallback
    raise HTTPException(503, "Kein kompatibler lokaler Bildgenerator verfügbar")


def _generation_model(model_id, prompt):
    if model_id != "auto":
        return registry_call(registry.get_model, model_id)
    return _auto_generation_model(prompt)


def _edit_model(model_id, *, multi_reference=False, modern=False):
    if model_id != "auto":
        return registry_call(registry.get_model, model_id)
    data = registry_call(registry.load_registry)
    # Prefer the locally proven Osaurus edit checkpoint for automatic edits.
    # Disabled, unavailable or manually chosen models are never overridden.
    preference = (
        "mflux-osaurus-qwen-image-2.1-edit",
        "mflux-qwen-image-2.1-edit",
        "mflux-qwen-image-edit-2511",
    )
    candidates = sorted(
        data["models"],
        key=lambda item: (
            preference.index(item["id"]) if item["id"] in preference else len(preference),
            item["id"] != data["default_model"],
        ),
    )
    edit_candidates = [model for model in candidates
                       if "image_edit" in model.get("capabilities", [])
                       and (not multi_reference or model.get("provider") == "mflux")
                       and (not modern or model.get("model_family") == "qwen-image21-edit")]
    enabled_candidates = [model for model in edit_candidates if model["enabled"]]
    if not edit_candidates:
        raise HTTPException(503, "Kein Bildbearbeitungsmodell konfiguriert")
    if not enabled_candidates:
        raise HTTPException(503, "Bildbearbeitungsmodelle sind deaktiviert. Bitte in den Modelleinstellungen aktivieren.")
    for model in enabled_candidates:
        ready, _ = availability(model)
        if ready:
            return model
    raise HTTPException(
        503,
        "Kein einsatzbereites Bildbearbeitungsmodell: Lokale Modellgewichte oder Runtime-Verfügbarkeit prüfen.",
    )


def _resolved_steps(model, requested_steps, quality=None):
    if requested_steps is not None:
        return requested_steps

    if quality is not None:
        return resolve_image_profile(model, quality)["steps"]

    default_steps = int(model["default_steps"])

    if str(model.get("model_family") or "") == "qwen-image21":
        return max(40, default_steps)

    return default_steps


def _generate_result(
    request,
    *,
    provider_options=None,
    prepared_callback=None,
    saving_callback=None,
    resolved=None,
    resolved_callback=None,
):
    global _running

    if resolved is None:
        resolved = _resolve_generation(request)
    model = copy.deepcopy(resolved["model"])
    params = copy.deepcopy(resolved["params"])
    profile = copy.deepcopy(resolved["quality_profile"])
    if request.seed is not None:
        params["seed"] = request.seed
    if resolved_callback:
        resolved_callback({**copy.deepcopy(resolved), "params": copy.deepcopy(params)})
    OUTPUT.mkdir(parents=True, exist_ok=True)
    image_id = f"{int(time.time())}-{secrets.token_hex(6)}"
    path = OUTPUT / f"{image_id}.png"
    if prepared_callback:
        prepared_callback(model, params, path)
    _running = model["id"]
    chat_was_loaded = False

    try:
        if model["provider"] == "mlxserve":
            chat_was_loaded = _chat_server_loaded()

            if chat_was_loaded:
                print(
                    "[image-memory] stopping chat server before MLX-Serve image generation",
                    flush=True,
                )
                _chat_server_command("stop")
                time.sleep(1)

        runtime_coordinator.ensure_model_load_allowed(
            "image",
        )
        run_provider(model, params, path, **(provider_options or {}))

    finally:
        active_error = sys.exc_info()[1]
        cleanup_error = None

        if model["provider"] == "mlxserve":
            try:
                print(
                    "[image-memory] unloading MLX-Serve image model",
                    flush=True,
                )
                _unload_mlxserve_model_and_wait(model)
            except Exception as exc:
                cleanup_error = exc
                print(
                    f"[image-memory] ERROR: image model unload failed: {exc}",
                    flush=True,
                )

            if chat_was_loaded:
                if cleanup_error is None:
                    try:
                        print(
                            "[image-memory] restarting chat server",
                            flush=True,
                        )
                        _chat_server_command("start")
                    except Exception as exc:
                        print(
                            f"[image-memory] ERROR: chat server restart failed: {exc}",
                            flush=True,
                        )
                else:
                    print(
                        "[image-memory] chat restart skipped because the "
                        "image model is still resident",
                        flush=True,
                    )

        _running = None

        if cleanup_error is not None and active_error is None:
            raise RuntimeError(
                "MLX-Serve-Image-Modell konnte nicht vollständig entladen "
                "werden; Chat-Neustart wurde zum Speicherschutz übersprungen"
            ) from cleanup_error
    if saving_callback:
        saving_callback()
    return {
        "id": image_id, "path": str(path), "mime_type": "image/png",
        "width": params["width"], "height": params["height"],
        "prompt": params["prompt"], "original_prompt": request.original_prompt or request.prompt,
        "negative_prompt": params.get("negative_prompt"),
        "model": model["id"], "resolved_model": model["id"],
        "requested_model": resolved["requested_model"],
        "provider": model["provider"], "model_family": model["model_family"],
        "quantization": model["quantization"],
        "loras": [l for l in model["loras"] if l["enabled"]],
        "guidance": params["guidance"], "seed": params["seed"],
        "steps": params["steps"], "quality": params.get("quality"),
        "auto_size": params["auto_size"], "quality_profile": profile,
        "requested_width": request.width, "requested_height": request.height,
        "created_at": time.time(),
    }


def _resolve_generation(request):
    """Resolve once; the resulting model/config and provider params are immutable batch inputs."""
    if request.width % 16 or request.height % 16:
        raise HTTPException(422, "width and height must be divisible by 16")
    model = _generation_model(request.model, request.prompt)
    if request.sdxl_vae_mode is not None and model["provider"] != "sdxl":
        raise HTTPException(422, "Der VAE-Diagnosemodus ist nur für SDXL verfügbar")
    maximum_edge = 1216 if model["model_family"] == "sdxl" else 1024
    if request.width > maximum_edge or request.height > maximum_edge:
        raise HTTPException(
            422,
            f"width and height must not exceed {maximum_edge} for this model",
        )
    params = request.model_dump(exclude={"original_prompt", "sdxl_vae_mode"})
    if request.sdxl_vae_mode is not None:
        params["sdxl_vae_mode"] = request.sdxl_vae_mode
    negative_prompt = str(request.negative_prompt or "").strip()
    if negative_prompt:
        params["negative_prompt"] = negative_prompt
    else:
        params.pop("negative_prompt", None)
    profile = resolve_image_profile(model, request.quality) if request.quality else None
    params["steps"] = (
        request.steps if request.steps is not None
        else profile["steps"] if profile else _resolved_steps(model, None)
    )
    params["guidance"] = (
        request.guidance
        if request.guidance is not None
        else profile["guidance"] if profile else model["default_guidance"]
    )
    if request.auto_size and profile and profile.get("long_edge"):
        params["width"], params["height"] = dimensions_for_long_edge(
            request.width, request.height, profile["long_edge"],
        )
    params["seed"] = request.seed if request.seed is not None else secrets.randbelow(2**31 - 1)
    if model["id"] == registry.JUGGERNAUT_XL_ID:
        # Ragnarok sampler recommended by its creator (SDE variant);
        # the available Diffusers preset uses Karras sigmas.
        params["scheduler"] = "dpmpp-2m-sde-karras"
    if model["provider"] == "diffusionkit" and params["steps"] > 8:
        raise HTTPException(422, "FLUX.1-schnell/DiffusionKit unterstützt maximal 8 Steps")
    if model["model_family"] == "flux2-klein" and "base" not in model["base_model"] and params["guidance"] != 1:
        raise HTTPException(422, "FLUX.2 Klein distilled benötigt Guidance 1")
    if model["model_family"] == "z-image-turbo" and params["guidance"] != 0:
        raise HTTPException(422, "Z-Image Turbo unterstützt keine CFG-Guidance; 0 verwenden")
    return {"model": copy.deepcopy(model), "params": params,
            "quality_profile": profile, "requested_model": request.model, "requested_seed": request.seed}


def _prepare_fast_edit_source(source, model):
    """Create an aspect-preserving working copy for large Qwen edits."""
    if model.get("model_family") != "qwen-image-edit":
        return source, None

    from PIL import Image

    OUTPUT.mkdir(parents=True, exist_ok=True)
    target_pixels = 512 * 768

    with Image.open(source) as image:
        width, height = image.size

        if width * height <= target_pixels:
            return source, None

        scale = (target_pixels / (width * height)) ** 0.5

        # Round down to multiples of 16 so the pixel budget is not exceeded.
        resized_width = max(256, int((width * scale) // 16) * 16)
        resized_height = max(256, int((height * scale) // 16) * 16)

        working = OUTPUT / (
            f".edit-source-{int(time.time())}-"
            f"{secrets.token_hex(6)}.png"
        )

        converted = image.convert("RGB")
        converted.thumbnail(
            (resized_width, resized_height),
            Image.Resampling.LANCZOS,
        )
        converted.save(working, "PNG")

        print(
            f"[image-edit] "
            f"original={width}x{height} "
            f"working={converted.width}x{converted.height} "
            f"pixels={converted.width * converted.height}",
            flush=True,
        )

    return working, working


def _edit_result(request, **kwargs):
    temporary_sources = []
    try:
        return _edit_result_inner(request, temporary_sources=temporary_sources, **kwargs)
    finally:
        for source in temporary_sources:
            source.unlink(missing_ok=True)


def _edit_result_inner(
    request,
    *,
    provider_options=None,
    prepared_callback=None,
    saving_callback=None,
    resolved=None,
    resolved_callback=None,
    temporary_sources=None,
):
    global _running

    is_reference = request.semantic_operation == 'reference_generate'
    if resolved is None:
        try:
            model = _edit_model(request.model, multi_reference=len(request.source_paths or []) > 1,
                                modern=len(request.source_paths or []) > 3 or any(
                                    getattr(request, key) is not None for key in ('mask_path', 'auto_mask', 'strength',
                                        'use_kv_cache', 'use_step_cache', 'step_cache_threshold', 'enhance_prompt', 'verify')))
        except HTTPException:
            if is_reference:
                raise HTTPException(503, 'Kein kompatibles lokales Modell für Referenzbilder verfügbar.') from None
            raise
        if is_reference:
            ready, _ = availability(model)
            if not model.get('enabled', True) or not ready:
                raise HTTPException(503, 'Kein kompatibles lokales Modell für Referenzbilder verfügbar.')
    else:
        model = copy.deepcopy(resolved['model'])

    if "image_edit" not in model.get("capabilities", []):
        raise HTTPException(
            422,
            "Das gewählte Image-Modell unterstützt keine Bildbearbeitung",
        )

    sources = [validate_edit_source(value) for value in (request.source_paths or [request.source_path])]
    source = sources[0]
    if request.region_edit and (model.get('provider') != 'mflux'
                                or model.get('model_family') != 'qwen-image21-edit'):
        raise HTTPException(422, 'Bereichsbearbeitung benötigt ein MFLUX Qwen 2.1 Edit-Modell')
    prepared_sources = []
    region_crop = None
    region_mask = None
    from PIL import Image, ImageOps
    if request.region_edit:
        # Never resize the whole image into the model. Crop the selected
        # region before any provider load, preserving the untouched original.
        safe_mask = validate_edit_source(request.mask_path)
        region_source, region_mask, region_crop = prepare_region(source, safe_mask, OUTPUT)
        temporary_sources.extend((region_source, region_mask))
        prepared_sources.append(region_source)
    for original in ([] if request.region_edit else sources):
        if model.get('model_family') == 'qwen-image21-edit' or len(sources) > 1:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            working = OUTPUT / ('.edit-source-' + secrets.token_hex(12) + '.png')
            temporary_sources.append(working)
            with Image.open(original) as image:
                image = ImageOps.exif_transpose(image).convert('RGBA')
                edge = (resolve_image_profile(model, request.quality or 'standard').get('long_edge') or 768)
                image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
                with open(working, 'xb', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
                    image.save(stream, 'PNG')
            working.chmod(0o600)
        else:
            working, temporary = _prepare_fast_edit_source(original, model)
            if temporary:
                temporary_sources.append(temporary)
        prepared_sources.append(working)
    edit_source = prepared_sources[0]
    params = (copy.deepcopy(resolved['params']) if resolved else request.model_dump(exclude={
        'semantic_operation', 'reference_mode', 'reference_artifact_id', 'original_prompt',
        'width', 'height', 'auto_size', 'precision_edit', 'region_edit', 'region_feather_px'}))
    params["source_path"] = str(edit_source)
    if request.source_paths:
        params['source_paths'] = [str(value) for value in prepared_sources]
    if (
        request.precision_edit
        and not is_reference
        and not request.mask_path
        and not request.auto_mask
        and len(sources) == 1
        and model.get("provider") == "mflux"
        and model.get("model_family") == "qwen-image21-edit"
    ):
        inferred = infer_auto_mask_target(request.prompt)
        if inferred:
            params["auto_mask"] = inferred
            # An inferred mask is optional. Unsupported CLI versions must
            # keep the original unmasked edit rather than failing a job.
            params["_precision_auto_mask_inferred"] = True
    if request.mask_path and request.region_edit:
        params['mask_path'] = str(region_mask)
    elif request.mask_path:
        mask = validate_edit_source(request.mask_path)
        with Image.open(mask) as image, Image.open(source) as original:
            if image.size != original.size:
                raise HTTPException(422, 'Die Maske muss zur Größe des ersten Referenzbilds passen')
            mask_pixels = image.convert('L')
            # A completely black mask means no area was selected; do not
            # consume RAM/model time or silently edit the entire image.
            if mask_pixels.getbbox() is None:
                raise HTTPException(422, 'Maske enthält keinen markierten Bereich')
            working_mask = OUTPUT / ('.edit-source-' + secrets.token_hex(12) + '.png')
            temporary_sources.append(working_mask)
            with Image.open(edit_source) as working:
                mask_pixels.resize(working.size, Image.Resampling.NEAREST).save(working_mask)
            working_mask.chmod(0o600)
        params['mask_path'] = str(working_mask)

    # Qwen must render at the prepared working resolution too. Resizing only
    # the source image is not enough because MFLUX may otherwise select a
    # substantially larger output canvas.
    if resolved is None and model.get("model_family") in {"qwen-image-edit", "qwen-image21-edit"}:
        from PIL import Image

        with Image.open(edit_source) as prepared_image:
            params["width"], params["height"] = prepared_image.size

    if resolved is None:
        params['steps'] = _resolved_steps(model, request.steps, request.quality)
        profile = resolve_image_profile(model, request.quality) if request.quality else None
        params['guidance'] = request.guidance if request.guidance is not None else profile['guidance'] if profile else model['default_guidance']
        params['seed'] = request.seed if request.seed is not None else secrets.randbelow(2**31 - 1)
        if is_reference and request.width is not None:
            # Qwen's advertised width/height flags support a target canvas.
            # Other edit providers retain their existing source-size policy.
            if model.get('model_family') in {'qwen-image-edit', 'qwen-image21-edit'}:
                edge = min(1024, (profile or {}).get('long_edge') or 768)
                params['width'], params['height'] = dimensions_for_long_edge(request.width, request.height, edge)
    elif request.seed is not None:
        params['seed'] = request.seed
    if request.region_edit:
        # Keep the existing 18 GB preflight and active watchdog intact.
        # Disable optional model default step caches for this edit only.
        model = {**model, 'step_cache_default': False}
        params['_region_low_ram'] = True
    if model.get('model_family') == 'qwen-image21-edit':
        params['width'] = max(256, (params['width'] // 32) * 32)
        params['height'] = max(256, (params['height'] // 32) * 32)
        if params['guidance'] < 1:
            raise HTTPException(422, 'Qwen 2.1 Edit benötigt Guidance mindestens 1')
    if resolved_callback:
        # Freeze the original edit request, not the temporary Qwen crop/mask.
        # Every reroll prepares fresh working files from the same source and
        # original user mask. Pin the resolved settings so model defaults may
        # change without silently altering the repeated edit.
        replay_request = request.model_dump() if is_reference else {
            **request.model_dump(), 'model': model['id'],
            'steps': params['steps'], 'guidance': params['guidance'],
        }
        canonical = {'model': copy.deepcopy(model), 'params': {**copy.deepcopy(params), 'source_path': str(source),
                     **({'source_paths': [str(value) for value in sources]} if request.source_paths else {}),
                     **({'mask_path': request.mask_path} if request.mask_path else {})},
                     'request': replay_request, 'operation': 'edit',
                     'quality_profile': resolved.get('quality_profile') if resolved else profile,
                     'requested_model': request.model, 'requested_seed': request.seed}
        resolved_callback(canonical)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    image_id = f"{int(time.time())}-{secrets.token_hex(6)}"
    path = OUTPUT / f"{image_id}.png"
    if prepared_callback:
        prepared_callback(model, params, path)
    _running = model["id"]
    try:
        runtime_coordinator.ensure_model_load_allowed(
            "image",
        )
        run_provider(model, params, path, **(provider_options or {}))
        if request.region_edit:
            composite_region(source, validate_edit_source(request.mask_path),
                             path, region_crop, path,
                             feather_px=request.region_feather_px)
    finally:
        _running = None
    if saving_callback:
        saving_callback()

    from PIL import Image

    with Image.open(path) as image:
        width, height = image.size

    # Optional, bounded advisory; never triggers a silent retry or masks out
    # legitimate global edits, and never claims semantic compliance.
    quality_check = image_change_advisory(source, path) if not is_reference else None
    source_image_id = comparison_image_id(source, OUTPUT) if not is_reference else None

    return {
        **({"source_image_id": source_image_id} if source_image_id else {}),
        **({"quality_check": quality_check} if quality_check else {}),
        "id": image_id,
        "path": str(path),
        "mime_type": "image/png",
        "width": width,
        "height": height,
        "prompt": request.prompt,
        "source_path": str(source),
        **({"source_paths": [str(value) for value in sources]} if request.source_paths else {}),
        "reference_count": len(sources),
        "model": model["id"],
        "provider": model["provider"],
        "model_family": model["model_family"],
        "quantization": model["quantization"],
        "loras": [l for l in model["loras"] if l["enabled"]],
        "guidance": params["guidance"],
        "seed": params["seed"],
        "steps": params["steps"],
        "quality": request.quality,
        'semantic_operation': request.semantic_operation,
        'reference_used': is_reference,
        'reference_mode': request.reference_mode,
        'reference_relation': request.reference_mode,
        'reference_artifact_id': request.reference_artifact_id,
        'original_prompt': request.original_prompt or request.prompt,
        "created_at": time.time(),
    }


def _upscale_result(
    request,
    *,
    provider_options=None,
    prepared_callback=None,
    saving_callback=None,
):
    global _running

    source = validate_edit_source(request.source_path)

    OUTPUT.mkdir(parents=True, exist_ok=True)

    image_id = f"{int(time.time())}-{secrets.token_hex(6)}"
    path = OUTPUT / f"{image_id}.png"

    command = realesrgan_command(
        source,
        path,
        preset=request.preset,
        tile=request.tile,
    )

    params = {
        "source_path": str(source),
        "preset": request.preset,
        "tile": request.tile,
    }

    model = {
        "id": "realesrgan",
        "provider": "realesrgan",
        "model_family": "realesrgan",
    }

    if prepared_callback:
        prepared_callback(model, params, path)

    options = provider_options or {}
    cancel_event = options.get("cancel_event")
    process_callback = options.get("process_callback")
    progress_callback = options.get("progress_callback")

    if cancel_event is not None and cancel_event.is_set():
        raise ProviderCancelled("Image job was cancelled")

    _running = "realesrgan"
    process = None

    try:
        runtime_coordinator.ensure_model_load_allowed(
            "image-upscale",
        )
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )

        if process_callback:
            process_callback(process)

        deadline = time.monotonic() + 840
        output_lines = []

        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise ProviderCancelled("Image job was cancelled")

            line = process.stdout.readline()

            if line:
                line = line.strip()
                output_lines.append(line)

                if len(output_lines) > 200:
                    output_lines = output_lines[-200:]

                if line.endswith("%"):
                    try:
                        percent = float(line[:-1].strip())
                    except ValueError:
                        percent = None

                    if percent is not None and progress_callback:
                        progress_callback({
                            "phase": "generate",
                            "step": max(
                                0,
                                min(
                                    1000,
                                    round(percent * 10),
                                ),
                            ),
                            "total_steps": 1000,
                        })

            returncode = process.poll()

            if returncode is not None:
                remainder = process.stdout.read()
                if remainder:
                    output_lines.extend(
                        line.strip()
                        for line in remainder.splitlines()
                        if line.strip()
                    )
                break

            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "Real-ESRGAN-Auftrag hat das Zeitlimit überschritten"
                )

            if not line:
                time.sleep(0.05)

        if cancel_event is not None and cancel_event.is_set():
            raise ProviderCancelled("Image job was cancelled")

        if process.returncode != 0:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

            message = (
                "\n".join(output_lines[-100:]).strip()
                or "Real-ESRGAN konnte das Bild nicht hochskalieren"
            )

            raise RuntimeError(message[-4000:])

    finally:
        if process is not None:
            terminate_process_tree(process)

        if process_callback:
            process_callback(None)

        _running = None

    if not path.is_file():
        raise RuntimeError(
            "Real-ESRGAN hat keine Ausgabedatei erzeugt"
        )

    if progress_callback:
        progress_callback({
            "phase": "save",
            "step": 1000,
            "total_steps": 1000,
        })

    if saving_callback:
        saving_callback()

    from PIL import Image

    with Image.open(source) as image:
        source_width, source_height = image.size

    with Image.open(path) as image:
        width, height = image.size

    return {
        "id": image_id,
        "path": str(path),
        "mime_type": "image/png",
        "width": width,
        "height": height,
        "source_width": source_width,
        "source_height": source_height,
        "source_path": str(source),
        "preset": request.preset,
        "scale": (
            2
            if request.preset == "photo-2x"
            else 4
        ),
        "tile": request.tile,
        "model": (
            "realesrgan-x4plus-anime"
            if request.preset == "anime-4x"
            else "realesrgan-x4plus"
        ),
        "provider": "realesrgan",
        "model_family": "realesrgan",
        "created_at": time.time(),
    }


@app.post("/upscale")
def upscale(request: Upscale):
    with exclusive():
        try:
            return _upscale_result(request)
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(
                500,
                _provider_failure(exc),
            ) from exc



@app.post("/generate")
def generate(request: Generate):
    with exclusive():
        try:
            # Resolve once; do not reroute between the memory handoff and the job.
            resolved = _resolve_generation(request)
            sdxl_job = resolved["model"].get("provider") == "sdxl"
            with runtime_coordinator.image_runtime(
                None, force_chat_unload=sdxl_job
            ) as preflight:
                try:
                    return _generate_result(request, resolved=resolved)
                finally:
                    if sdxl_job:
                        try:
                            shutdown_sdxl_worker()
                        except Exception:
                            # Never restore a chat model on top of SDXL if
                            # the image worker could not be terminated.
                            if preflight is not None:
                                preflight["suppress_chat_restore"] = True
                            raise
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(503, _provider_failure(exc)) from exc


@app.post("/edit")
def edit(request: Edit):
    with exclusive():
        try:
            return _edit_result(request)
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(503, _provider_failure(exc)) from exc


def _job_snapshot(job):
    snapshot = {
        key: value
        for key, value in job.items()
        if not key.startswith("_")
    }
    if snapshot.get("status") == "completed":
        snapshot["progress"] = 1.0
    step = snapshot.get("current_step")
    total = snapshot.get("total_steps")
    if isinstance(step, int) and isinstance(total, int) and total > 0:
        snapshot["progress"] = min(1.0, max(0.0, step / total))
    return snapshot


_TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}


def _update_job(job_id, **changes):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return False

        current_status = job.get("status")
        requested_status = changes.get("status")

        if (
            current_status in _TERMINAL_JOB_STATUSES
            and requested_status is not None
            and requested_status != current_status
        ):
            return False

        job.update(changes)
        return True


def _provider_progress(job_id, event):
    changes = {}
    if isinstance(event.get("provider_timing"), dict):
        changes["provider_timing"] = event["provider_timing"]
    phase = event.get("phase")
    if phase:
        changes["phase"] = str(phase)
    if phase in {"save", "complete", "generated"}:
        changes["status"] = "saving"
    elif phase:
        changes["status"] = "running"
    if event.get("step") is not None and event.get("total_steps") is not None:
        changes["current_step"] = event["step"]
        changes["total_steps"] = event["total_steps"]
        if event["total_steps"] > 0:
            changes["progress"] = min(1.0, max(0.0, event["step"] / event["total_steps"]))
    elif isinstance(event.get("progress"), (int, float)):
        progress = float(event["progress"])
        changes["progress"] = min(1.0, max(0.0, progress / 100 if progress > 1 else progress))
    if changes:
        _update_job(job_id, **changes)


def _run_image_job(job_id, operation, request, *, resolved=None, release_lock=True):
    global _active_job_id

    output_path = None
    timings = ImageJobTimings()
    cancel_event = _jobs[job_id]["_cancel_event"]

    def prepared(model, params, path):
        nonlocal output_path
        output_path = path
        _update_job(
            job_id,
            model=model["id"],
            provider=model['provider'],
            model_family=model['model_family'],
            total_steps=(
                params.get("steps")
                if operation != "upscale"
                else 1000
            ),
            _output_path=path,
        )

    def process_changed(process):
        _update_job(job_id, _process=process)
        if process is not None:
            _update_job(job_id, status="running")

    provider_options = {
        "cancel_event": cancel_event,
        "process_callback": process_changed,
        "progress_callback": lambda event: _provider_progress(job_id, event),
    }

    try:
        if cancel_event.is_set():
            raise ProviderCancelled("Image job was cancelled")
        _update_job(
            job_id, status="queued", phase="waiting_for_resources",
            progress=0.0, started_at=time.time(),
        )
        # Resolve image provider before allocating heavy runtime resources.
        # SDXL always gets an exclusive chat handoff, even if the current
        # estimated free percentage still looks healthy.
        if operation == "generate" and resolved is None:
            resolved = _resolve_generation(request)
        selected = resolved.get("model") if isinstance(resolved, dict) else None
        sdxl_job = bool(operation == "generate"
                        and selected and selected.get("provider") == "sdxl")
        # The 48-GB unified-memory image editor can load a large Qwen Edit
        # model even for 512x512 crops.  A resident chat model competes for
        # the same RAM and can cause abrupt swap spikes after image admission.
        # Release chat exclusively for opt-in masked region edits, just as
        # for SDXL.  The existing image_runtime safety checks still govern
        # admission and conditional restoration of chat after completion.
        region_qwen_job = bool(
            operation == "edit" and getattr(request, "region_edit", False)
        )
        with runtime_coordinator.image_runtime(
            cancel_event,
            force_chat_unload=(sdxl_job or region_qwen_job),
            exclusive_models=True,
        ) as preflight:
            # The image service retains a warm SDXL worker between SDXL
            # requests. It must not remain resident alongside a new Qwen,
            # FLUX, video-derived edit or upscaler provider within this same
            # service. Release it under the coordinator lease first.
            if not sdxl_job and sdxl_worker_running():
                shutdown_sdxl_worker()
                if sdxl_worker_running():
                    raise RuntimeError(
                        "SDXL-Worker konnte vor dem Modellwechsel nicht entladen werden"
                    )
            timings.mark("resources_acquired")
            _update_job(job_id, status="loading", phase="loading")
            if operation == "edit":
                execute = _edit_result
            elif operation == "upscale":
                execute = _upscale_result
            else:
                execute = _generate_result

            timings.mark("execution_started")
            try:
                result = execute(
                    request,
                    provider_options=provider_options,
                    prepared_callback=prepared,
                    saving_callback=lambda: _update_job(job_id, status="saving", phase="saving"),
                    **({"resolved": resolved} if resolved is not None else {}),
                    **({"resolved_callback": lambda canonical: _update_job(job_id, _canonical=canonical)}
                       if operation in {"generate", "edit"} else {}),
                )
            finally:
                # Do not restart chat on top of a still-resident SDXL pipeline.
                # This runs before the image_runtime context restores chat.
                if sdxl_job:
                    try:
                        shutdown_sdxl_worker()
                    except Exception:
                        if preflight is not None:
                            preflight["suppress_chat_restore"] = True
                        raise
        timings.mark("execution_finished")
        if cancel_event.is_set():
            raise ProviderCancelled("Image job was cancelled")
        with _jobs_lock:
            job = _jobs[job_id]
            for key in ("variant_group_id", "variant_index", "variant_count", "source_generation_job_id"):
                if key in job:
                    result[key] = job[key]
            total_steps = job.get("total_steps")
        completed = {
            "status": "completed", "phase": "completed", "current_step": total_steps,
            "progress": 1.0, "result": result, "finished_at": time.time(),
        }
        if operation in {"generate", "edit"}:
            from image_variants import persist_record
            canonical = _jobs[job_id].get("_canonical")
            completed["variants_available"] = canonical is not None
            completed["result"] = {**result, "variants_available": canonical is not None}
            if canonical is not None:
                try:
                    persist_record(sys.modules[__name__], "job-" + job_id, {
                        "job": {**_job_snapshot(_jobs[job_id]), **completed}, "canonical": canonical,
                    })
                except Exception:
                    # Reproduction metadata is optional: preserve the completed image.
                    completed["variants_available"] = False
                    completed["result"]["variants_available"] = False
        _update_job(job_id, **completed)
    except (ProviderCancelled, runtime_coordinator.CoordinationCancelled):
        if output_path is not None:
            output_path.unlink(missing_ok=True)
        _update_job(
            job_id,
            status="cancelled",
            result=None,
            error=None,
            finished_at=time.time(),
        )
    except Exception as exc:
        if output_path is not None:
            output_path.unlink(missing_ok=True)
        if cancel_event.is_set():
            _update_job(
                job_id, status="cancelled", result=None,
                error=None, finished_at=time.time(),
            )
        else:
            detail = str(exc.detail) if isinstance(exc, HTTPException) else _provider_failure(exc)
            _update_job(
                job_id, status="failed", result=None,
                error=detail, finished_at=time.time(), **getattr(exc, 'diagnosis', {}),
            )
    finally:
        _update_job(job_id, _process=None, performance_timings=timings.report())
        with _jobs_lock:
            if _active_job_id == job_id:
                _active_job_id = None
        if release_lock:
            _lock.release()


def _prune_jobs_locked():
    terminal = [
        job
        for job in _jobs.values()
        if job.get("status") in {"completed", "failed", "cancelled"}
    ]
    terminal.sort(key=lambda job: job.get("finished_at") or 0)
    while len(_jobs) >= _MAX_RETAINED_JOBS and terminal:
        _jobs.pop(terminal.pop(0)["id"], None)


@app.post("/jobs", status_code=202)
def create_image_job(request: ImageJobCreate):
    global _active_job_id

    try:
        if request.operation == "edit":
            image_request = Edit.model_validate(
                request.payload
            )
        elif request.operation == "upscale":
            image_request = Upscale.model_validate(
                request.payload
            )
        else:
            image_request = Generate.model_validate(
                request.payload
            )
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()) from exc

    if not _lock.acquire(blocking=False):
        raise HTTPException(
            409,
            "Ein Image-Auftrag läuft bereits. Bitte dessen Abschluss abwarten.",
        )

    job_id = secrets.token_hex(12)
    created_at = time.time()
    cancel_event = threading.Event()
    job = {
        "id": job_id,
        "operation": request.operation,
        "chat_id": request.chat_id,
        "run_id": request.run_id or job_id,
        "chat_revision": request.chat_revision,
        "status": "queued",
        "phase": "queued",
        "model": None,
        "current_step": None,
        "total_steps": (
            1000
            if request.operation == "upscale"
            else image_request.steps
        ),
        "progress": 0.0,
        "result": None,
        "error": None,
        "created_at": created_at,
        "started_at": None,
        "finished_at": None,
        "_cancel_event": cancel_event,
        "_process": None,
        "_output_path": None,
    }
    thread = threading.Thread(
        target=_run_image_job,
        args=(job_id, request.operation, image_request),
        name=f"image-job-{job_id}",
        daemon=True,
    )
    job["_thread"] = thread
    if request.operation == 'edit' and image_request.semantic_operation == 'reference_generate':
        job.update(semantic_operation='reference_generate', reference_mode=image_request.reference_mode, reference_relation=image_request.reference_mode, reference_used=True)

    with _jobs_lock:
        _prune_jobs_locked()
        _jobs[job_id] = job
        _active_job_id = job_id
        response = _job_snapshot(job)

    try:
        thread.start()
    except Exception:
        with _jobs_lock:
            _jobs.pop(job_id, None)
            _active_job_id = None
        _lock.release()
        raise

    return response


@app.get("/jobs/{job_id}")
def image_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Image-Job nicht gefunden")
        return _job_snapshot(job)


def _cancel_job(job):
    """Signal one active image job for cancellation."""
    if job.get("status") not in {
        "queued",
        "loading",
        "running",
        "saving",
    }:
        return None, None

    job["_cancel_event"].set()
    return job.get("_process"), job.get("_thread")


def cancel_chat_image_jobs(chat_id: str, chat_revision: int | None = None):
    """Cancel active image jobs owned by one chat/revision."""
    targets = []

    with _jobs_lock:
        for job in _jobs.values():
            if job.get("chat_id") != chat_id:
                continue
            if (
                chat_revision is not None
                and job.get("chat_revision") != chat_revision
            ):
                continue

            process, thread = _cancel_job(job)
            if process is not None or thread is not None:
                targets.append((job["id"], process, thread))

    cancelled = []

    for job_id, process, thread in targets:
        if process is not None:
            terminate_process_tree(process)

        if thread is not None:
            thread.join(
                timeout=PROCESS_TERMINATION_TIMEOUT * 2 + 1
            )
            if thread.is_alive():
                raise HTTPException(
                    503,
                    "Image-Job konnte nicht rechtzeitig beendet werden",
                )

        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is not None:
                cancelled.append(_job_snapshot(job))

    return cancelled


@app.post("/jobs/cancel-chat")
def cancel_chat_image_jobs_api(request: dict):
    chat_id = request.get("chat_id")
    chat_revision = request.get("chat_revision")

    if not isinstance(chat_id, str) or not chat_id.strip():
        raise HTTPException(
            422,
            "Chat-ID fehlt",
        )

    if (
        chat_revision is not None
        and (
            isinstance(chat_revision, bool)
            or not isinstance(chat_revision, int)
            or chat_revision < 0
        )
    ):
        raise HTTPException(
            422,
            "Ungültige Chat-Revision",
        )

    cancelled = cancel_chat_image_jobs(
        chat_id,
        chat_revision,
    )

    return {
        "chat_id": chat_id,
        "chat_revision": chat_revision,
        "cancelled": cancelled,
        "cancelled_count": len(cancelled),
    }



@app.post("/jobs/{job_id}/cancel")
def cancel_image_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Image-Job nicht gefunden")
        if job.get("status") not in {
            "queued",
            "loading",
            "running",
            "saving",
        }:
            raise HTTPException(
                409,
                "Image-Job kann nicht mehr abgebrochen werden",
            )
        process, thread = _cancel_job(job)

    if process is not None:
        terminate_process_tree(process)
    if thread is not None:
        thread.join(timeout=PROCESS_TERMINATION_TIMEOUT * 2 + 1)
        if thread.is_alive():
            raise HTTPException(503, "Image-Job konnte nicht rechtzeitig beendet werden")

    with _jobs_lock:
        return _job_snapshot(_jobs[job_id])

# POST /jobs/variants coexists with GET /jobs/{job_id}.
create_image_variants = install_image_variants(sys.modules[__name__])
