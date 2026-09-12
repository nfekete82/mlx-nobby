"""Native, local FLUX image service. Images stay on disk, never in API payloads."""
import secrets
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
import image_registry as registry
from image_providers import (
    PROCESS_TERMINATION_TIMEOUT,
    ProviderCancelled,
    availability,
    run_provider,
    terminate_process_tree,
)
from local_security import LocalRequestGuard

OUTPUT = Path.home() / ".config/mlx-web/images"
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
    model: str = "auto"
    width: int = Field(default=512, ge=256, le=1024)
    height: int = Field(default=512, ge=256, le=1024)
    steps: int | None = Field(default=None, ge=1, le=50)
    guidance: float | None = Field(default=None, ge=0, le=10)
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)


class Edit(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    prompt: str = Field(min_length=3, max_length=2000)
    source_path: str
    model: str = "auto"
    steps: int | None = Field(default=None, ge=1, le=50)
    guidance: float | None = Field(default=None, ge=0, le=10)
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)


class ImageJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["generate", "edit"]
    payload: dict


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
        "status": "busy" if _running or _active_job_id else "ready",
        "models": [m["id"] for m in data["models"] if m["enabled"]],
        "loaded": bool(_running), "running_model": _running,
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
        return {"ok": True, "loaded": False, "detail": "Image-Modelle werden nach jedem Auftrag freigegeben"}


def _provider_failure(exc):
    return (
        str(exc)
        if isinstance(exc, RuntimeError)
        else "Image-Provider konnte kein gültiges PNG erzeugen"
    )


def _generate_result(
    request,
    *,
    provider_options=None,
    prepared_callback=None,
    saving_callback=None,
):
    global _running

    if request.width % 16 or request.height % 16:
        raise HTTPException(422, "width and height must be divisible by 16")
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
    if prepared_callback:
        prepared_callback(model, params, path)
    _running = model["id"]
    try:
        run_provider(model, params, path, **(provider_options or {}))
    finally:
        _running = None
    if saving_callback:
        saving_callback()
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


def _edit_result(
    request,
    *,
    provider_options=None,
    prepared_callback=None,
    saving_callback=None,
):
    global _running

    model = registry_call(registry.get_model, request.model)

    if "image_edit" not in model.get("capabilities", []):
        raise HTTPException(
            422,
            "Das gewählte Image-Modell unterstützt keine Bildbearbeitung",
        )

    source = validate_edit_source(request.source_path)
    params = request.model_dump()
    params["source_path"] = str(source)
    params["steps"] = request.steps if request.steps is not None else model["default_steps"]
    params["guidance"] = request.guidance if request.guidance is not None else model["default_guidance"]
    params["seed"] = request.seed if request.seed is not None else secrets.randbelow(2**31 - 1)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    image_id = f"{int(time.time())}-{secrets.token_hex(6)}"
    path = OUTPUT / f"{image_id}.png"
    if prepared_callback:
        prepared_callback(model, params, path)
    _running = model["id"]
    try:
        run_provider(model, params, path, **(provider_options or {}))
    finally:
        _running = None
    if saving_callback:
        saving_callback()

    from PIL import Image

    with Image.open(path) as image:
        width, height = image.size

    return {
        "id": image_id,
        "path": str(path),
        "mime_type": "image/png",
        "width": width,
        "height": height,
        "prompt": request.prompt,
        "source_path": str(source),
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


@app.post("/generate")
def generate(request: Generate):
    with exclusive():
        try:
            return _generate_result(request)
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
    step = snapshot.get("current_step")
    total = snapshot.get("total_steps")
    if isinstance(step, int) and isinstance(total, int) and total > 0:
        snapshot["progress"] = min(1.0, max(0.0, step / total))
    return snapshot


def _update_job(job_id, **changes):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.update(changes)


def _provider_progress(job_id, event):
    changes = {}
    phase = event.get("phase")
    if phase in {"save", "complete", "generated"}:
        changes["status"] = "saving"
    elif phase:
        changes["status"] = "running"
    if event.get("step") is not None and event.get("total_steps") is not None:
        changes["current_step"] = event["step"]
        changes["total_steps"] = event["total_steps"]
    if changes:
        _update_job(job_id, **changes)


def _run_image_job(job_id, operation, request):
    global _active_job_id

    output_path = None
    cancel_event = _jobs[job_id]["_cancel_event"]

    def prepared(model, params, path):
        nonlocal output_path
        output_path = path
        _update_job(
            job_id,
            model=model["id"],
            total_steps=params.get("steps"),
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
        _update_job(job_id, status="loading", started_at=time.time())
        execute = _edit_result if operation == "edit" else _generate_result
        result = execute(
            request,
            provider_options=provider_options,
            prepared_callback=prepared,
            saving_callback=lambda: _update_job(job_id, status="saving"),
        )
        if cancel_event.is_set():
            raise ProviderCancelled("Image job was cancelled")
        _update_job(
            job_id,
            status="completed",
            result=result,
            finished_at=time.time(),
        )
    except ProviderCancelled:
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
        detail = str(exc.detail) if isinstance(exc, HTTPException) else _provider_failure(exc)
        _update_job(
            job_id,
            status="failed",
            result=None,
            error=detail,
            finished_at=time.time(),
        )
    finally:
        _update_job(job_id, _process=None)
        with _jobs_lock:
            if _active_job_id == job_id:
                _active_job_id = None
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
        image_request = (
            Edit.model_validate(request.payload)
            if request.operation == "edit"
            else Generate.model_validate(request.payload)
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
        "status": "queued",
        "model": None,
        "current_step": None,
        "total_steps": image_request.steps,
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


@app.post("/jobs/{job_id}/cancel")
def cancel_image_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Image-Job nicht gefunden")
        if job.get("status") not in {"queued", "loading", "running", "saving"}:
            raise HTTPException(409, "Image-Job kann nicht mehr abgebrochen werden")
        job["_cancel_event"].set()
        process = job.get("_process")
        thread = job.get("_thread")

    if process is not None:
        terminate_process_tree(process)
    if thread is not None:
        thread.join(timeout=PROCESS_TERMINATION_TIMEOUT * 2 + 1)
        if thread.is_alive():
            raise HTTPException(503, "Image-Job konnte nicht rechtzeitig beendet werden")

    with _jobs_lock:
        return _job_snapshot(_jobs[job_id])
