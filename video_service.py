"""Persistent local video jobs backed by the official headless LTX 2.5 runtime."""
import json
import os
import re
import secrets
import subprocess
import tempfile
import threading
import time
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

import video_registry as registry
from local_security import LocalRequestGuard
from video_providers import (
    ProviderCancelled, availability, generate, i2v_aspect_ratio, i2v_source_size,
    i2v_target_size, validate_first_frame,
)


ROOT = Path.home() / ".config/mlx-web"
OUTPUT = ROOT / "videos"
JOBS = ROOT / "video-jobs"
PROJECT_DIR = Path(__file__).resolve().parent
MLX_MANAGER = PROJECT_DIR / "scripts/mlx"
MLX_SERVER_LABEL = "de.nobby.mlx-server"
IMAGE_HEALTH_URL = os.environ.get("IMAGE_SERVICE_URL", "http://127.0.0.1:8030").rstrip("/") + "/health"
ACTIVE = {"queued", "loading", "encoding", "generating", "upscaling", "decoding", "muxing"}
TERMINAL = {"completed", "failed", "cancelled"}
QUALITY_PROFILES = {
    "fast": {"resolution": "540p", "steps": 11},
    "standard": {"resolution": "720p", "steps": 11},
    "quality": {"resolution": "1080p", "steps": 11},
}
LANDSCAPE_SIZES = {
    "540p": (1024, 576), "720p": (1280, 704), "1080p": (1920, 1088),
}
SUPPORTED_DURATIONS = {5, 6, 8, 10}
_lock = threading.Lock()
_jobs_lock = threading.RLock()
_jobs = {}


class VideoPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    prompt: str = Field(min_length=3, max_length=4000)
    model: str = "auto"
    resolution: Literal["540p", "720p", "1080p"] | None = None
    duration: int = Field(default=5)
    fps: Literal[24] = 24
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    first_frame: str | None = None
    resize_mode: Literal["contain", "cover"] | None = None
    quality: Literal["fast", "standard", "quality"] | None = None
    width: int | None = None
    height: int | None = None
    frames: int | None = None
    steps: int = 11
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"

    @model_validator(mode="after")
    def valid_ltx_options(self):
        if self.duration not in SUPPORTED_DURATIONS:
            raise ValueError("LTX-Dauer muss 5, 6, 8 oder 10 Sekunden sein")
        if self.width is not None and (self.width <= 0 or self.width % 32):
            raise ValueError("Video width muss positiv und durch 32 teilbar sein")
        if self.height is not None and (self.height <= 0 or self.height % 32):
            raise ValueError("Video height muss positiv und durch 32 teilbar sein")
        return self


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["t2v", "i2v"]
    payload: VideoPayload
    chat_id: str = Field(min_length=1)
    run_id: str | None = None
    chat_revision: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def valid_operation(self):
        supplied = self.payload.model_fields_set
        quality = self.payload.quality or "standard"
        profile = QUALITY_PROFILES[quality]
        if "resolution" not in supplied or self.payload.resolution is None:
            self.payload.resolution = profile["resolution"]
        self.payload.steps = profile["steps"]
        if self.operation == "i2v" and not self.payload.first_frame:
            raise ValueError("I2V benötigt ein verwaltetes First-Frame-Artefakt")
        if self.operation == "t2v" and self.payload.first_frame:
            raise ValueError("T2V akzeptiert kein First Frame")
        if self.operation == "t2v" and self.payload.resize_mode is not None:
            raise ValueError("resize_mode ist nur für I2V verfügbar")
        if self.operation == "i2v":
            source = validate_first_frame(self.payload.first_frame)
            source_width, source_height = i2v_source_size(source)
            self.payload.aspect_ratio = i2v_aspect_ratio(source_width, source_height)
            expected = i2v_target_size(source_width, source_height, quality)
            if ("width" in supplied) != ("height" in supplied):
                raise ValueError("I2V width und height müssen gemeinsam angegeben werden")
            if "width" not in supplied:
                self.payload.width, self.payload.height = expected
            if self.payload.resize_mode is None:
                self.payload.resize_mode = "contain"
        else:
            landscape = LANDSCAPE_SIZES[self.payload.resolution]
            if "width" not in supplied:
                self.payload.width, self.payload.height = landscape
            self.payload.aspect_ratio = "9:16" if self.payload.height > self.payload.width else "16:9"
        self.payload.frames = self.payload.duration * self.payload.fps + 1
        return self


def _public(job):
    return {key: value for key, value in job.items() if not key.startswith("_")}


def _job_file(job_id):
    return JOBS / f"{job_id}.json"


def _persist(job):
    JOBS.mkdir(parents=True, exist_ok=True)
    data = json.dumps(_public(job), indent=2, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{job['id']}-", suffix=".json", dir=JOBS)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, _job_file(job["id"]))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load_jobs():
    JOBS.mkdir(parents=True, exist_ok=True)
    with _jobs_lock:
        for path in JOBS.glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if job.get("status") in ACTIVE:
                    job.update(status="failed", error="Video-Service wurde während des Jobs neu gestartet", finished_at=time.time())
                    _persist(job)
                job.update(_cancel_event=threading.Event(), _runtime=None, _thread=None)
                _jobs[job["id"]] = job
            except (OSError, ValueError, KeyError, TypeError):
                continue


@asynccontextmanager
async def lifespan(_app):
    registry.load_registry()
    _load_jobs()
    try:
        yield
    finally:
        with _jobs_lock:
            active = [
                job for job in _jobs.values()
                if job.get("status") in ACTIVE
            ]
            for job in active:
                job["_cancel_event"].set()
            runtimes = [job.get("_runtime") for job in active]
            threads = [job.get("_thread") for job in active]
            for job in active:
                job["_runtime"] = None
        for runtime in runtimes:
            unload(runtime)
        for thread in threads:
            if thread is not None:
                thread.join(timeout=25)


app = FastAPI(title="MLX Nobby Video", lifespan=lifespan)
app.add_middleware(LocalRequestGuard)


def _chat_loaded():
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{MLX_SERVER_LABEL}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _chat_command(action):
    result = subprocess.run(
        ["/bin/bash", str(MLX_MANAGER), action], cwd=PROJECT_DIR,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stdout.strip() or f"mlx {action} fehlgeschlagen")[-4000:])


def _image_idle():
    try:
        with urllib.request.urlopen(IMAGE_HEALTH_URL, timeout=10) as response:
            health = json.loads(response.read())
        return health.get("status") == "ready" and not health.get("loaded")
    except Exception as exc:
        raise RuntimeError("Image-Service-Zustand konnte nicht geprüft werden") from exc


def _memory_snapshot():
    snapshot = {"ram_used_bytes": None, "swap_used_bytes": None}
    try:
        output = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5, check=True).stdout
        page_size = int(re.search(r"page size of (\d+) bytes", output).group(1))
        pages = {}
        for label, value in re.findall(r"^([^:]+):\s+(\d+)\.", output, re.MULTILINE):
            pages[label] = int(value)
        used = sum(pages.get(label, 0) for label in (
            "Pages active", "Pages inactive", "Pages wired down",
            "Pages occupied by compressor", "Pages speculative",
        ))
        snapshot["ram_used_bytes"] = used * page_size
    except Exception:
        pass
    try:
        output = subprocess.run(
            ["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True, timeout=5, check=True,
        ).stdout
        match = re.search(r"used = ([0-9.]+)([MG])", output)
        if match:
            multiplier = 1024**2 if match.group(2) == "M" else 1024**3
            snapshot["swap_used_bytes"] = int(float(match.group(1)) * multiplier)
    except Exception:
        pass
    return snapshot


def _update(job_id, **changes):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        if job.get("status") in TERMINAL and changes.get("status") not in {None, job.get("status")}:
            return
        job.update(changes)
        _persist(job)


def _phase_status(phase):
    value = str(phase or "").lower()
    if value in {"starting", "loading", "loading_model", "validating_request"}:
        return "loading"
    if "encod" in value:
        return "encoding"
    if "upscal" in value or "refin" in value:
        return "upscaling"
    if "decod" in value:
        return "decoding"
    if "mux" in value or "final" in value:
        return "muxing"
    if value in {"inference", "denoising", "generating", "running"}:
        return "generating"
    return None


def _normalized_progress(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    value = float(value)
    if value > 1:
        value /= 100
    return min(1.0, max(0.0, value))


def _run(job_id, request):
    job = _jobs[job_id]
    cancel = job["_cancel_event"]
    output = None
    chat_was_loaded = False
    before = _memory_snapshot()
    peak = dict(before)
    try:
        _update(
            job_id, status="loading", phase="loading", progress=0.0,
            started_at=time.time(), memory_before=before,
        )
        model = registry.get_model(request.payload.model)
        ready, reason = availability(model)
        if not ready:
            raise RuntimeError(reason)
        if not _image_idle():
            raise RuntimeError("Qwen Image ist geladen oder ein Image-Job läuft; Video-Job sicher abgebrochen")
        chat_was_loaded = _chat_loaded()
        if chat_was_loaded:
            _chat_command("stop")
            time.sleep(1)
        if cancel.is_set():
            raise ProviderCancelled("Video job was cancelled")
        video_id = secrets.token_hex(12)
        output = OUTPUT / f"{video_id}.mp4"

        def runtime_changed(runtime):
            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id]["_runtime"] = runtime

        def progress_changed(event):
            current = _memory_snapshot()
            for key in peak:
                if current.get(key) is not None:
                    peak[key] = max(peak.get(key) or 0, current[key])
            changes = {"memory_peak": peak}
            phase = str(event.get("phase") or "")
            if phase:
                changes["phase"] = phase
                status = _phase_status(phase)
                if status:
                    changes["status"] = status
            step, total = event.get("step"), event.get("total_steps")
            if isinstance(step, int) and isinstance(total, int) and 0 < step <= total:
                changes.update(current_step=step, total_steps=total)
            progress = _normalized_progress(event.get("progress"))
            if progress is not None:
                changes["progress"] = progress
            elif isinstance(step, int) and isinstance(total, int) and 0 < step <= total:
                changes["progress"] = step / total
            _update(job_id, **changes)

        def phase_changed(phase):
            changes = {"phase": phase}
            status = _phase_status(phase)
            if status:
                changes["status"] = status
            _update(job_id, **changes)

        media = generate(
            model, request.payload.model_dump(), output,
            cancel_event=cancel, response_callback=runtime_changed,
            progress_callback=progress_changed,
            phase_callback=phase_changed,
        )
        if cancel.is_set():
            raise ProviderCancelled("Video job was cancelled")
        after = _memory_snapshot()
        result = {
            "id": video_id, "path": str(output), "mime_type": "video/mp4",
            "prompt": request.payload.prompt, "model": model["id"],
            "repository": model["repository"], "provider": model["provider"],
            "model_family": model["model_family"], "quantization": model["quantization"],
            "pipeline": model["pipeline"], "steps": request.payload.steps,
            "seed": request.payload.seed, "operation": request.operation,
            "quality": request.payload.quality or "standard",
            "resolution": request.payload.resolution, "first_frame": request.payload.first_frame,
            "created_at": time.time(), "memory_before": before, "memory_peak": peak,
            "memory_after": after, **media,
        }
        _update(
            job_id, status="completed", phase="completed", current_step=8,
            total_steps=8, progress=1.0, result=result, error=None,
            finished_at=time.time(), memory_after=after,
        )
    except ProviderCancelled:
        if output:
            output.unlink(missing_ok=True)
        _update(job_id, status="cancelled", result=None, error=None, finished_at=time.time(), memory_after=_memory_snapshot())
    except Exception as exc:
        if output:
            output.unlink(missing_ok=True)
        if cancel.is_set():
            _update(job_id, status="cancelled", result=None, error=None, finished_at=time.time())
        else:
            _update(job_id, status="failed", result=None, error=str(exc)[-4000:], finished_at=time.time(), memory_after=_memory_snapshot())
    finally:
        if chat_was_loaded:
            try:
                _chat_command("start")
            except Exception as exc:
                current = _jobs.get(job_id)
                if current:
                    _update(job_id, restore_error=f"Chat-Restore fehlgeschlagen: {exc}")
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["_runtime"] = None
        _lock.release()


@app.get("/health")
def health():
    running = next((job["id"] for job in _jobs.values() if job.get("status") in ACTIVE), None)
    return {"ok": True, "status": "busy" if running else "ready", "active_job_id": running, "offline": True}


@app.get("/models")
def models():
    data = registry.load_registry()
    described = []
    for model in data["models"]:
        ready, reason = availability(model)
        described.append(model | {"available": ready, "availability_note": reason, "local_path": str(registry.model_path(model))})
    return data | {"models": described, "offline": True}


@app.post("/jobs", status_code=202)
def create_job(request: JobCreate):
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, "Ein Video-Job läuft bereits")
    job_id = secrets.token_hex(12)
    job = {
        "id": job_id, "operation": request.operation, "chat_id": request.chat_id,
        "run_id": request.run_id or job_id, "chat_revision": request.chat_revision,
        "status": "queued", "phase": "queued", "model": request.payload.model,
        "current_step": None, "total_steps": 8, "progress": 0.0,
        "result": None, "error": None,
        "payload": request.payload.model_dump(), "created_at": time.time(),
        "started_at": None, "finished_at": None, "_cancel_event": threading.Event(),
        "_runtime": None, "_thread": None,
    }
    thread = threading.Thread(target=_run, args=(job_id, request), daemon=True, name=f"video-job-{job_id}")
    job["_thread"] = thread
    with _jobs_lock:
        _jobs[job_id] = job
        _persist(job)
    try:
        thread.start()
    except Exception:
        _lock.release()
        raise
    return _public(job)


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    with _jobs_lock:
        if job_id not in _jobs:
            raise HTTPException(404, "Video-Job nicht gefunden")
        return _public(_jobs[job_id])


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Video-Job nicht gefunden")
        if job.get("status") not in ACTIVE:
            raise HTTPException(409, "Video-Job kann nicht mehr abgebrochen werden")
        job["_cancel_event"].set()
        thread = job.get("_thread")
    if thread is not None:
        thread.join(timeout=20)
    with _jobs_lock:
        return _public(_jobs[job_id])
