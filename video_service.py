"""Persistent local video jobs backed by the official headless LTX 2.5 runtime."""
from ai_lifecycle_gate import AIAdmissionGuard

import video_long
import video_segmented
import video_rolling
import ai_lifecycle_gate as gate
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

import video_registry as registry
from video_profiles import preflight_profile, profile_capabilities
from quality_profiles import resolve_video_profile
import runtime_coordinator
import video_multi_image
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
ACTIVE = {"queued", "loading", "encoding", "generating", "upscaling", "decoding", "muxing"}
TERMINAL = {"completed", "failed", "cancelled"}
RESOLUTION_SIZES = {
    "preview": {
        "16:9": (384, 256),
        "9:16": (256, 384),
    },
    "540p": {
        "16:9": (1024, 576),
        "9:16": (576, 1024),
    },
    "720p": {
        "16:9": (1280, 704),
        "9:16": (704, 1280),
    },
    "1080p": {
        "16:9": (1920, 1088),
        "9:16": (1088, 1920),
    },
}
SUPPORTED_DURATIONS_BY_RESOLUTION = {key: set(values) for key, values in video_long.SUPPORTED.items()}

_lock = threading.Lock()
_jobs_lock = threading.RLock()
_jobs = {}

# Progress events may arrive several times per second. Keep in-memory job
# polling live, but avoid a disk fsync for every unchanged/volatile update.
PROGRESS_PERSIST_INTERVAL_SECONDS = max(
    0.25, float(os.environ.get("MLX_VIDEO_PROGRESS_PERSIST_SECONDS", "1.5"))
)
MEMORY_SAMPLE_INTERVAL_SECONDS = 2.0
_VOLATILE_PROGRESS_FIELDS = frozenset({
    "progress", "current_step", "total_steps", "memory_peak", "last_activity_at", "phase_progress",
})


class VideoImage(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    path: str
    frame_index: int | None = Field(default=None, ge=0, strict=True)
    strength: float = Field(default=1.0, ge=0, le=1)


class VideoPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    prompt: str = Field(min_length=3, max_length=4000)
    model: str = "auto"
    profile: Literal["standard", "uncensored"] = "standard"
    resolution: Literal["preview", "540p", "720p", "1080p"] | None = None
    duration: int = Field(default=5)
    fps: Literal[8, 24] = 24
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    first_frame: str | None = None
    # Applies only to segmented image-to-video jobs with an original still.
    identity_lock: bool = True
    identity_strength: float = Field(default=0.30, ge=0.10, le=0.60)
    # Rolling I2V text-only conditioning; None inherits the legacy identity_lock behavior.
    face_guidance: Literal["off", "minimal", "full"] | None = None
    # API-only experiment; None preserves checkpoint-native still preprocessing.
    i2v_image_crf: int | None = Field(default=None, strict=True, ge=0, le=0)
    continuation_mode: Literal["segmented", "rolling"] = "segmented"
    images: list[VideoImage] = Field(default_factory=list, max_length=5)
    multi_image_mode: Literal["keyframes", "scenes"] | None = None
    resume_from: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")
    resize_mode: Literal["contain", "cover"] | None = None
    quality: Literal["preview", "fast", "standard", "quality"] | None = None
    width: int | None = None
    height: int | None = None
    frames: int | None = None
    steps: int | None = Field(default=None, ge=1)
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"

    @model_validator(mode="after")
    def valid_ltx_options(self):
        if self.quality == "preview":
            self.resolution = "preview"
            self.duration = 2
            self.fps = 8

        effective_resolution = (
            self.resolution
            or resolve_video_profile(
                {"model_family": "ltx-2.5"}, self.quality or "standard",
            )["resolution"]
        )
        allowed_durations = SUPPORTED_DURATIONS_BY_RESOLUTION[
            effective_resolution
        ]

        if self.duration not in allowed_durations:
            allowed = ", ".join(
                str(value)
                for value in sorted(allowed_durations)
            )
            raise ValueError(
                f"LTX-Dauer für {effective_resolution} "
                f"muss {allowed} Sekunden sein"
            )

        if self.width is not None and (self.width <= 0 or self.width % 32):
            raise ValueError("Video width muss positiv und durch 32 teilbar sein")
        if self.height is not None and (self.height <= 0 or self.height % 32):
            raise ValueError("Video height muss positiv und durch 32 teilbar sein")
        return self


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["t2v", "i2v", "multi_i2v"]
    payload: VideoPayload
    chat_id: str = Field(min_length=1)
    run_id: str | None = None
    chat_revision: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def valid_operation(self):
        supplied = self.payload.model_fields_set
        quality = self.payload.quality or "standard"
        profile = resolve_video_profile(
            registry.get_model(self.payload.model), quality,
        )

        multi = self.operation == "multi_i2v"
        if multi:
            if not 2 <= len(self.payload.images) <= 5 or not self.payload.multi_image_mode:
                raise ValueError("Multi-Image-to-Video benötigt 2–5 Bilder und einen Modus")
            if self.payload.first_frame:
                raise ValueError("Multi-Image verwendet images statt first_frame")
            if registry.get_model(self.payload.model).get("provider") != "ltx-mlx":
                raise ValueError("Multi-Image-to-Video benötigt den installierten LTX-MLX-Provider")
            if self.payload.multi_image_mode == "keyframes" and not _multi_capabilities()["native_keyframes"]:
                raise ValueError("Die installierte LTX-MLX-Version unterstützt keine nativen Keyframes; Szenen verbinden verwenden")
            for image in self.payload.images:
                validate_first_frame(image.path)
        elif self.payload.images or self.payload.multi_image_mode:
            raise ValueError("Multi-Image-Parameter benötigen multi_i2v")
        if self.payload.continuation_mode == "rolling":
            video_rolling.plan(self.payload.duration, self.payload.resolution or profile["resolution"], self.payload.fps)
            if multi or self.payload.profile != "standard" or registry.get_model(self.payload.model).get("provider") != "ltx-mlx":
                raise ValueError("Rolling-Window benötigt ein einzelnes Standard-LTX-MLX-Video")
        if self.payload.face_guidance is not None and (
                self.operation != "i2v" or self.payload.continuation_mode != "rolling"):
            raise ValueError("Gesichtstextführung ist nur für Rolling-I2V verfügbar")
        if self.payload.i2v_image_crf is not None and (
                self.operation != "i2v" or self.payload.continuation_mode != "rolling"):
            raise ValueError("Experimentelles Bild-CRF ist nur für Rolling-I2V verfügbar")
        long_video = (video_rolling.needed(self.payload.model_dump()) or
                      video_long.needed({"duration": self.payload.duration, "resolution": self.payload.resolution or profile["resolution"], "fps": self.payload.fps}))
        if long_video and (multi or self.payload.profile != "standard" or registry.get_model(self.payload.model).get("provider") != "ltx-mlx"):
            raise ValueError("Automatische Fortsetzung benötigt natives Standard-LTX-MLX und ein einzelnes Ausgangsvideo")
        if self.payload.resume_from and self.payload.multi_image_mode != "scenes" and not long_video:
            raise ValueError("Nur Szenenjobs und automatische Langvideos können fortgesetzt werden")

        if quality == "preview" and self.operation != "t2v":
            raise ValueError(
                "Video-Vorschau ist nur für Text-zu-Video verfügbar"
            )
        if "resolution" not in supplied or self.payload.resolution is None:
            self.payload.resolution = profile["resolution"]
        if "steps" in supplied and self.payload.steps != profile["steps"]:
            raise ValueError(
                "Die installierte LTX-Distilled-Pipeline verwendet feste "
                f"{profile['steps']} Steps"
            )
        self.payload.steps = profile["steps"]
        if self.operation == "i2v" and not self.payload.first_frame:
            raise ValueError("I2V benötigt ein verwaltetes First-Frame-Artefakt")
        if self.operation == "t2v" and self.payload.first_frame:
            raise ValueError("T2V akzeptiert kein First Frame")
        if self.operation == "t2v" and self.payload.resize_mode is not None:
            raise ValueError("resize_mode ist nur für I2V verfügbar")
        if self.operation == "i2v" or multi:
            source = validate_first_frame(self.payload.images[0].path if multi else self.payload.first_frame)
            source_width, source_height = i2v_source_size(source)

            if "aspect_ratio" not in supplied:
                self.payload.aspect_ratio = i2v_aspect_ratio(
                    source_width,
                    source_height,
                )
                expected = i2v_target_size(
                    source_width,
                    source_height,
                    quality,
                )
            else:
                expected = _video_dimensions(
                    self.payload.resolution,
                    self.payload.aspect_ratio,
                )
            if ("width" in supplied) != ("height" in supplied):
                raise ValueError("I2V width und height müssen gemeinsam angegeben werden")
            if "width" not in supplied:
                self.payload.width, self.payload.height = expected
            if self.payload.resize_mode is None:
                self.payload.resize_mode = "contain"
        else:
            width, height = _video_dimensions(
                self.payload.resolution,
                self.payload.aspect_ratio,
            )
            if quality == "preview" or "width" not in supplied:
                self.payload.width, self.payload.height = width, height
            self.payload.aspect_ratio = "9:16" if self.payload.height > self.payload.width else "16:9"
        self.payload.frames = self.payload.duration * self.payload.fps + 1
        if long_video and (self.payload.width, self.payload.height) != _video_dimensions(self.payload.resolution, self.payload.aspect_ratio):
            raise ValueError("Automatische Fortsetzung erhält die volle Profilauflösung; abweichende Dimensionen sind nicht erlaubt")
        if multi:
            positions = video_multi_image.frame_positions(len(self.payload.images), self.payload.frames)
            for index, image in enumerate(self.payload.images):
                if self.payload.multi_image_mode == "scenes":
                    if image.frame_index not in {None, 0} or image.strength != 1:
                        raise ValueError("Szenenbilder verwenden Frame 0 und Stärke 1")
                    image.frame_index = 0
                else:
                    if image.frame_index is None:
                        image.frame_index = positions[index]
                    if image.frame_index >= self.payload.frames:
                        raise ValueError("Keyframe liegt außerhalb des Videos")
            if self.payload.multi_image_mode == "keyframes":
                indices = [image.frame_index for image in self.payload.images]
                if indices != sorted(set(indices)):
                    raise ValueError("Keyframes müssen streng aufsteigend und eindeutig sein")
        return self


def _multi_capabilities():
    from video_providers_mlx import LTX_MLX_RUNTIME_ROOT
    return video_multi_image.keyframe_capabilities(LTX_MLX_RUNTIME_ROOT)


def _multi_source_versions(payload):
    versions = []
    for image in payload.images:
        stat = Path(image.path).stat()
        versions.append({"path": image.path, "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    if video_segmented.needed(payload.model_dump()) and payload.first_frame:
        stat = Path(payload.first_frame).stat()
        versions.append({"path": payload.first_frame, "bytes": stat.st_size,
                         "mtime_ns": stat.st_mtime_ns})
    return versions


def _video_dimensions(resolution, aspect_ratio):
    ratios = RESOLUTION_SIZES[resolution]
    return ratios.get(aspect_ratio or "16:9", ratios["16:9"])


def _job_total_steps(payload):
    return 2 if payload.quality == "preview" else 8


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
                segmented = JOBS / "segmented" / str(job.get("id", "")) / "checkpoint.json"
                rolling = JOBS / "rolling" / str(job.get("id", "")) / "checkpoint.json"
                checkpoint = (rolling if rolling.is_file() else
                              segmented if segmented.is_file()
                              else JOBS / "long" / str(job.get("id", "")) / "checkpoint.json")
                if job.get("status") in ACTIVE and checkpoint.is_file():
                    import managed_process
                    owner = ("video:rolling:" if checkpoint == rolling else
                             "video:segmented:" if checkpoint == segmented else "video:long:") + job["id"]
                    managed_process.stop_all(owner=owner)
                    for partial in checkpoint.parent.glob("*.partial.mp4"):
                        partial.unlink(missing_ok=True)
                if checkpoint.is_file() and (not job.get("cancel_requested") or job.get("cancel_reason") == "lifecycle"):
                    saved = json.loads(checkpoint.read_text())
                    stages = saved.get("stages") or []
                    strategy = (saved.get("plan") or {}).get("strategy")
                    confirmed = (sum(stage.get("seconds", 0) for stage in (saved.get("plan") or {}).get("stages", [])[:len(stages)])
                                 if strategy == "segmented-low-ram-v1"
                                 else sum(int(entry.get("seconds", 0)) for entry in stages)
                                 if strategy == video_rolling.STRATEGY
                                 else stages[-1]["info"]["timeline_seconds"] if stages else 0)
                    job.update(automatic_continuation=True, resumable=bool(stages), checkpoint_count=len(stages),
                               confirmed_duration=confirmed)
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
app.add_middleware(AIAdmissionGuard)
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
        changed = {key: value for key, value in changes.items() if job.get(key) != value}
        if not changed:
            return

        job.update(changed, updated_at=time.time())
        now = time.monotonic()
        # Persist lifecycle/phase/errors immediately. Pure progress and
        # sampled memory peaks can be reconstructed after a service restart;
        # native active jobs are already marked failed during recovery.
        persist_now = bool(set(changed) - _VOLATILE_PROGRESS_FIELDS)
        if not persist_now:
            last_persist = job.get("_last_persist_at")
            persist_now = (
                last_persist is None
                or now - last_persist >= PROGRESS_PERSIST_INTERVAL_SECONDS
            )
        if persist_now:
            _persist(job)
            job["_last_persist_at"] = now


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
    before = _memory_snapshot()
    peak = dict(before)
    try:
        _update(
            job_id, status="queued", phase="waiting_for_resources", progress=0.0,
            started_at=time.time(), memory_before=before,
        )
        model = registry.get_model(request.payload.model)
        ready, reason = availability(model)
        if not ready:
            raise RuntimeError(reason)
        handoff_started = time.monotonic()
        def record_admission(preflight):
            # Persist measured system-level diagnostics before admission can fail.
            # No prompts, model payload, or media contents are included.
            _update(
                job_id,
                memory_admission=preflight.get("memory_admission"),
                memory_before_admission=preflight.get("memory_before"),
                runtime_handoff={
                    "version": 3,
                    "timings_ms": dict(preflight.get("handoff_timings_ms") or {}),
                    "image_released": bool(preflight.get("image_released")),
                    "image_preserved": bool(preflight.get("image_preserved")),
                    "speech_released": bool(preflight.get("speech_released")),
                    "musetalk_released": bool(preflight.get("musetalk_released")),
                    "chat_released": bool(preflight.get("chat_released")),
                    "load_reserve_gb": preflight.get("load_reserve_gb"),
                    "hard_limit_reached": bool(preflight.get("hard_limit_reached")),
                },
            )

        with runtime_coordinator.video_runtime(
            cancel,
            chat_loaded=_chat_loaded,
            chat_command=_chat_command,
            restore_error=lambda exc: _update(
                job_id,
                restore_error=f"Chat-Restore fehlgeschlagen: {exc}",
            ),
            admission_observer=record_admission,
            exclusive_models=True,
        ) as preflight:
            # Persist only content-free timings and decisions. This includes
            # time waiting for the coordinator lease, not LTX model load time.
            runtime_handoff = {
                "version": 2,  # V2 distinguishes verified release counts from older records.
                "duration_ms": round((time.monotonic() - handoff_started) * 1000, 2),
                "timings_ms": dict(preflight.get("handoff_timings_ms") or {}),
                "image_released": bool(preflight.get("image_released")),
                "image_preserved": bool(preflight.get("image_preserved")),
                "speech_released": bool(preflight.get("speech_released")),
                "musetalk_released": bool(preflight.get("musetalk_released")),
                "chat_released": bool(preflight.get("chat_released")),
            }
            _update(
                job_id, status="loading", phase="loading",
                runtime_handoff=runtime_handoff,
            )
            if cancel.is_set():
                raise ProviderCancelled("Video job was cancelled")
            video_id = secrets.token_hex(12)
            OUTPUT.mkdir(parents=True, exist_ok=True)
            output = OUTPUT / f".{video_id}.partial.mp4"

            def runtime_changed(runtime):
                with _jobs_lock:
                    if job_id in _jobs:
                        _jobs[job_id]["_runtime"] = runtime

            last_memory_sample_at = time.monotonic()

            def sample_peak(current):
                for key in peak:
                    if current.get(key) is not None:
                        peak[key] = max(peak.get(key) or 0, current[key])

            is_long = (video_rolling.needed(request.payload.model_dump()) or
                       video_long.needed(request.payload.model_dump()))

            def progress_changed(event):
                nonlocal last_memory_sample_at
                changes = {}
                now = time.monotonic()
                if now - last_memory_sample_at >= MEMORY_SAMPLE_INTERVAL_SECONDS:
                    sample_peak(_memory_snapshot())
                    last_memory_sample_at = now
                    changes["memory_peak"] = dict(peak)
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
                if is_long:
                    changes.pop("progress", None)
                    changes["phase_progress"] = step / total if isinstance(step, int) and isinstance(total, int) and 0 <= step <= total and total > 0 else None
                    changes["progress"] = None
                    changes["last_activity_at"] = time.time()
                _update(job_id, **changes)

            def phase_changed(phase):
                changes = {"phase": phase}
                status = _phase_status(phase)
                if status:
                    changes["status"] = status
                _update(job_id, **changes)

            callbacks = dict(cancel_event=cancel, response_callback=runtime_changed,
                             progress_callback=progress_changed, phase_callback=phase_changed)
            if is_long and video_rolling.needed(request.payload.model_dump()):
                media = video_rolling.run(
                    model, request.payload.model_dump(), output, job_id=job_id,
                    checkpoints=JOBS / "rolling", resume_job=_jobs.get(request.payload.resume_from),
                    generate=generate,
                    update=lambda **changes: _update(job_id, **changes), **callbacks,
                )
            elif is_long and video_segmented.needed(request.payload.model_dump()):
                media = video_segmented.run(
                    model, request.payload.model_dump(), output, job_id=job_id,
                    checkpoints=JOBS / "segmented", resume_job=_jobs.get(request.payload.resume_from),
                    generate=generate,
                    update=lambda **changes: _update(job_id, **changes), **callbacks,
                )
            elif is_long:
                media = video_long.run(
                    model, request.payload.model_dump(), output, job_id=job_id,
                    checkpoints=JOBS / "long", resume_job=_jobs.get(request.payload.resume_from), generate=generate,
                    update=lambda **changes: _update(job_id, **changes), **callbacks,
                )
            elif request.payload.multi_image_mode == "scenes":
                media = video_multi_image.generate_scenes(
                    model, request.payload.model_dump(), output, job_id=job_id,
                    checkpoints=JOBS / "segments",
                    resume_job=_jobs.get(request.payload.resume_from), generate=generate,
                    update=lambda **changes: _update(job_id, **changes), **callbacks,
                )
            else:
                media = generate(model, request.payload.model_dump(), output, **callbacks)
            if cancel.is_set():
                raise ProviderCancelled("Video job was cancelled")
            after = _memory_snapshot()
            sample_peak(after)
            with gate.barrier(), _jobs_lock:
                gate.check()
                if cancel.is_set():
                    raise ProviderCancelled("Video job was cancelled")
                published = OUTPUT / f"{video_id}.mp4"
                os.replace(output, published)
                output = published
            result = {
                "id": video_id, "path": str(output), "mime_type": "video/mp4",
                "prompt": request.payload.prompt, "model": model["id"],
                "repository": model["repository"], "provider": model["provider"],
                "model_family": model["model_family"], "quantization": model["quantization"],
                "pipeline": resolve_video_profile(
                    model, request.payload.quality or "standard",
                )["pipeline"], "steps": request.payload.steps,
                "stage_1_steps": resolve_video_profile(
                    model, request.payload.quality or "standard",
                )["stage_1_steps"],
                "stage_2_steps": resolve_video_profile(
                    model, request.payload.quality or "standard",
                )["stage_2_steps"],
                "seed": request.payload.seed, "operation": request.operation,
                "quality": request.payload.quality or "standard",
                "resolution": request.payload.resolution, "first_frame": request.payload.first_frame,
                "multi_image_mode": request.payload.multi_image_mode,
                "images": [image.model_dump() for image in request.payload.images],
                "created_at": time.time(), "memory_before": before, "memory_peak": dict(peak),
                "memory_after": after, **media,
            }
            with _jobs_lock:
                if cancel.is_set():
                    raise ProviderCancelled("Video job was cancelled")
                _update(
                    job_id, status="completed", phase="completed",
                    current_step=_job_total_steps(request.payload),
                    total_steps=_job_total_steps(request.payload),
                    progress=1.0, result=result, error=None,
                    finished_at=time.time(), memory_after=after,
                    memory_peak=dict(peak),
                )
            # Final MP4 is published and the completed job is persisted.
            # Successful renders must not keep all source MP4 segments on disk.
            # Failed jobs retain their checkpoints for explicit resume.
            if video_rolling.needed(request.payload.model_dump()):
                try:
                    shutil.rmtree(JOBS / "rolling" / job_id)
                except OSError as cleanup_error:
                    _update(job_id, checkpoint_cleanup_warning=type(cleanup_error).__name__)
            if video_segmented.needed(request.payload.model_dump()) and not video_rolling.needed(request.payload.model_dump()):
                try:
                    shutil.rmtree(JOBS / "segmented" / job_id)
                except OSError as cleanup_error:
                    _update(job_id, checkpoint_cleanup_warning=type(cleanup_error).__name__)
    except (ProviderCancelled, runtime_coordinator.CoordinationCancelled):
        if output:
            output.unlink(missing_ok=True)
        lifecycle_interruption = video_long.needed(request.payload.model_dump()) and gate.blocked() and job.get("cancel_reason") != "user"
        _update(job_id, status="failed" if lifecycle_interruption else "cancelled", result=None,
                error="Durch Systemstopp unterbrochen; sichere Checkpoints können fortgesetzt werden" if lifecycle_interruption else None,
                finished_at=time.time(), memory_after=_memory_snapshot())
    except Exception as exc:
        if job.get("status") == "completed":
            # Model work and publication already succeeded. A subsequent
            # chat-restore/telemetry error must not delete a valid video.
            _update(job_id, restore_error=f"Nachbearbeitung fehlgeschlagen: {type(exc).__name__}")
            return
        if output:
            output.unlink(missing_ok=True)
        if cancel.is_set():
            _update(job_id, status="cancelled", result=None, error=None, finished_at=time.time())
        else:
            error = str(exc)[-4000:]
            if request.operation == "multi_i2v" and any(word in error.lower() for word in (
                "out of memory", "insufficient memory", "memory limit", "speicherbudget",
            )):
                error = ("Nicht genügend freier Speicher für LTX. Andere speicherintensive Programme schließen "
                         "oder Fast-Qualität verwenden. / Insufficient free memory for LTX. "
                         "Close memory-intensive apps or use Fast quality. "
                         "Fertige Szenen können fortgesetzt werden. / Completed scenes can be reused. " + error)
            _update(job_id, status="failed", result=None, error=error, finished_at=time.time(), memory_after=_memory_snapshot())
    finally:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["_runtime"] = None
        _lock.release()


@app.get("/health")
def health():
    running = next((job["id"] for job in _jobs.values() if job.get("status") in ACTIVE), None)
    active_generation = next((
        job["id"] for job in _jobs.values()
        if job.get("status") in ACTIVE
        and job.get("phase") != "waiting_for_resources"
    ), None)
    return {
        "ok": True,
        "status": "busy" if running else "ready",
        "active_job_id": running,
        "active_generation": bool(active_generation),
        "offline": True,
    }


@app.get("/models")
def models():
    data = registry.load_registry()
    described = []
    for model in data["models"]:
        ready, reason = availability(model)
        described.append(model | {"available": ready, "availability_note": reason, "local_path": str(registry.model_path(model))})
    default = next((m for m in described if m["id"] == data["default_model"]), {})
    return data | {"models": described, "offline": True, "multi_image": _multi_capabilities(),
                   "profiles": profile_capabilities(default)}


@app.post("/preflight")
def preflight(request: JobCreate):
    preflight_profile(request.payload.profile, registry.get_model(request.payload.model))
    if request.payload.resume_from:
        previous = _jobs.get(request.payload.resume_from)
        payload = request.payload.model_dump(exclude={"resume_from"})
        old_payload = dict((previous or {}).get("payload") or {})
        old_payload.pop("resume_from", None)
        # Jobs created before this opt-in field keep their default resume contract.
        old_payload.setdefault("i2v_image_crf", None)
        old_payload.setdefault("face_guidance", None)
        if (not previous or previous.get("status") not in {"failed", "cancelled"}
                or previous.get("chat_id") != request.chat_id or payload != old_payload):
            raise HTTPException(422, "Fortsetzen benötigt einen fehlgeschlagenen Job mit unveränderten Einstellungen und Quellen")
        if video_long.needed(request.payload.model_dump()) and (previous.get("status") == "cancelled" or previous.get("cancel_requested") and previous.get("cancel_reason") != "lifecycle"):
            raise HTTPException(422, "Explizit abgebrochene Langvideos werden nicht fortgesetzt")
        if video_rolling.needed(request.payload.model_dump()) and (previous.get("long_plan") or {}).get("strategy") != video_rolling.STRATEGY:
            raise HTTPException(422, "Nur Rolling-Window-Checkpoints können einen Rolling-Job fortsetzen")
        if (video_segmented.needed(request.payload.model_dump()) and
                not video_rolling.needed(request.payload.model_dump()) and
                (previous.get("long_plan") or {}).get("strategy") != "segmented-low-ram-v1"):
            raise HTTPException(422, "Ältere Extend-Checkpoints sind nicht kompatibel; bitte einen neuen RAM-sicheren Videojob starten")
        if ((previous.get("source_versions") is not None
             and previous["source_versions"] != _multi_source_versions(request.payload))
                or (previous.get("resolved_model") is not None
                    and previous["resolved_model"] != registry.get_model(request.payload.model)["id"])):
            raise HTTPException(422, "Quellbilder oder Modell wurden seit dem Szenenjob verändert")
    if video_rolling.needed(request.payload.model_dump()) or (video_long.needed(request.payload.model_dump()) and not video_segmented.needed(request.payload.model_dump())):
        video_long.runtime_version()
    return {"available": True, "profile": request.payload.profile}


@app.post("/jobs", status_code=202)
@gate.admitted
def create_job(request: JobCreate):
    preflight(request)
    source_versions = _multi_source_versions(request.payload)
    resolved_model = registry.get_model(request.payload.model)["id"]
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, "Ein Video-Job läuft bereits")
    job_id = secrets.token_hex(12)
    planner = (video_rolling.plan(request.payload.duration, request.payload.resolution, request.payload.fps)
               if video_rolling.needed(request.payload.model_dump())
               else video_segmented.plan(request.payload.duration, request.payload.resolution, request.payload.fps)
               if video_segmented.needed(request.payload.model_dump())
               else video_long.plan(request.payload.duration, request.payload.resolution, request.payload.fps))
    is_long = len(planner["stages"]) > 1
    job = {
        "id": job_id, "operation": request.operation, "chat_id": request.chat_id,
        "multi_image_mode": request.payload.multi_image_mode,
        "resolved_model": resolved_model,
        "source_versions": source_versions,
        "run_id": request.run_id or job_id, "chat_revision": request.chat_revision,
        "status": "queued", "phase": "queued", "model": request.payload.model,
        "current_step": None,
        "total_steps": _job_total_steps(request.payload),
        "progress": None if is_long else 0.0,
        **({"automatic_continuation": True, "long_plan": planner, "target_duration": request.payload.duration,
            "stage_count": len(planner["stages"]), "stage_number": 1, "confirmed_duration": 0,
            "phase_progress": None, "resumable": False} if is_long else {}),
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
def cancel_job(job_id: str, payload: dict | None = None):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Video-Job nicht gefunden")
        if job.get("status") not in ACTIVE:
            return _public(job)
        job["_cancel_event"].set()
        job["cancel_requested"] = True
        job["cancel_reason"] = "lifecycle" if (payload or {}).get("reason") == "lifecycle" else "user"
        _persist(job)
        thread = job.get("_thread")
    if thread is not None:
        thread.join(timeout=20)
    with _jobs_lock:
        return _public(_jobs[job_id])
