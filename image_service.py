"""Native, local image service. Images stay on disk, never in API payloads."""
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
import image_registry as registry
import subprocess
from image_providers import (
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
    negative_prompt: str = Field(default="", max_length=2000)
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


@asynccontextmanager
async def lifespan(app):
    registry.load_registry()
    try:
        yield
    finally:
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
        try:
            shutdown_sdxl_worker()
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
    preferred_ids = []
    if text_image:
        preferred_ids.append("mflux-qwen-image")
    elif realistic_style and human_subject:
        preferred_ids.append(registry.JUGGERNAUT_XL_ID)
    elif complex_prompt:
        preferred_ids.append("mflux-qwen-image")
    preferred_ids.append("mflux-z-image-turbo")

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
    return registry_call(registry.get_model)


def _generation_model(model_id, prompt):
    if model_id != "auto":
        return registry_call(registry.get_model, model_id)
    return _auto_generation_model(prompt)


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
    model = _generation_model(request.model, request.prompt)
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
        _update_job(job_id, status="loading", started_at=time.time())
        if operation == "edit":
            execute = _edit_result
        elif operation == "upscale":
            execute = _upscale_result
        else:
            execute = _generate_result

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
        "status": "queued",
        "model": None,
        "current_step": None,
        "total_steps": (
            1000
            if request.operation == "upscale"
            else image_request.steps
        ),
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
