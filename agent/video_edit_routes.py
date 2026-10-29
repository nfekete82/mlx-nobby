"""Local, opt-in LTX-MLX 0.18 Extend/Retake jobs for Nobby's own media library.

No uploads, arbitrary source paths, remote model IDs or free-form CLI arguments.
The existing source remains unchanged; edits create new managed video assets.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.request

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent import media_lifecycle
import runtime_coordinator
import ai_lifecycle_gate as gate
import managed_process

BASE = Path.home() / ".config/mlx-web"
JOB_DIR = BASE / "video-edits" / "jobs"
OUTPUT = BASE / "videos"
RUNTIME = Path.home() / ".local/share/mlx-nobby/ltx-2-mlx-v0.18.0"
MODEL = Path.home() / ".local/share/mlx-nobby/models/ltx-2.5-mlx-q4"
PROJECT = Path(__file__).resolve().parents[1]
VIDEO_HEALTH = "http://127.0.0.1:8060/health"
SERVER_LABEL = "de.nobby.mlx-server"
EXPECTED_HEAD = "b82b97e3d000e01361f8cfcb745244b15b89a521"
ACTIVE = {"queued", "preparing", "generating", "decoding", "cancelling"}
_jlock = threading.RLock()
_generation_lock = threading.Lock()
_jobs = {}


class ProgressTail:
    """Bounded regular-file reads; never wait for stdout or a newline."""
    def __init__(self, path):
        self.path = path
        self.reset()

    def reset(self):
        self.offset = 0
        self.pending = ""

    def read(self):
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            chunk = stream.read(65536)
            self.offset = stream.tell()
        if not chunk:
            return {}
        text = self.pending + chunk.decode("utf-8", errors="replace")
        records = re.split(r"[\r\n]", text)
        self.pending = records.pop()[-8192:]
        fields = {"last_activity_at": time.time()}
        for record in records:
            fields.update(parse_progress(record))
        fields.update(parse_progress(self.pending))
        return fields


def parse_progress(record):
    """LTX 0.18 samplers.py tqdm descriptions; fractions are phase-local."""
    record = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", record)
    match = re.search(r"(Denoising[^:]*):.*?\|\s*(\d+)\s*/\s*(\d+)", record)
    if match:
        current, total = int(match[2]), int(match[3])
        if total > 0 and 0 <= current <= total:
            return {"phase": "generating", "current_step": current, "total_steps": total,
                    "phase_progress": current / total, "progress": None,
                    "progress_scope": "phase", "progress_message": match[1]}
    # These messages come from the installed pipeline's verbose logger.
    lower = record.lower().strip().lstrip("[")
    for prefix, phase, message in (
        ("decoding", "decoding", "Video wird dekodiert"),
        ("loading", "loading", "LTX lädt Modelle"),
        ("encoding prompt", "encoding_prompt", "LTX kodiert den Prompt"),
        ("encoding", "encoding", "LTX kodiert Eingaben"),
        ("stage 1", "stage_1", "LTX Generierung · Stage 1"),
        ("stage 2", "stage_2", "LTX Verfeinerung · Stage 2"),
        ("saving", "saving", "Video wird gespeichert"),
    ):
        if lower.startswith(prefix):
            return {"phase": phase, "progress_message": message, "phase_progress": None,
                    "progress": None, "current_step": None, "total_steps": None}
    return {}


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source_kind: str = Field(pattern=r"^(video|talking_photo)$")
    source_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    operation: str = Field(pattern=r"^(extend|retake)$")
    prompt: str = Field(min_length=3, max_length=2000)
    seed: int = Field(default=42, ge=0, le=2147483647)
    distilled: bool = True
    extend_frames: int = Field(default=4, ge=1, le=12)
    start_seconds: float = Field(default=0.0, ge=0, le=60)
    end_seconds: float = Field(default=1.0, gt=0, le=60)

    @model_validator(mode="after")
    def valid_options(self):
        if self.operation == "retake" and self.start_seconds >= self.end_seconds:
            raise ValueError("Ende muss hinter dem Start liegen")
        return self


def source_path(kind, asset_id):
    try:
        path = media_lifecycle._expected_path(kind, asset_id)
        # The pathname itself must exist under the canonical managed root.
        raw = media_lifecycle._root_for(kind) / f"{asset_id}.mp4"
        if raw.is_symlink() or not raw.is_file() or raw.resolve() != path:
            raise ValueError("Quelle fehlt oder ist ein Symlink")
    except (ValueError, OSError) as exc:
        raise HTTPException(404, "Videoquelle nicht gefunden") from exc
    return path


def probe(path):
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
            "-show_entries", "stream=nb_read_frames,nb_frames,r_frame_rate,width,height",
            "-of", "json", str(path),
        ], capture_output=True, text=True, check=True, timeout=40)
        streams = json.loads(result.stdout).get("streams") or []
        stream = streams[0]
        count = int(stream.get("nb_read_frames") or stream.get("nb_frames") or 0)
        fps = stream["r_frame_rate"]
        numerator, denominator = map(int, fps.split("/"))
        rate = numerator / denominator
        width, height = int(stream["width"]), int(stream["height"])
    except (OSError, ValueError, KeyError, IndexError, subprocess.CalledProcessError, ZeroDivisionError) as exc:
        raise HTTPException(422, "Video-Metadaten konnten nicht gelesen werden") from exc
    if not (25 <= count <= 1441 and (count - 1) % 8 == 0 and abs(rate - 24.0) < 0.01):
        raise HTTPException(422, "Extend/Retake erfordert LTX-kompatible Videos mit 8k+1 Frames und 24 fps")
    if width % 64 or height % 64:
        raise HTTPException(422, "Extend/Retake benötigt Videoabmessungen als Vielfache von 64")
    return {"frames": count, "fps": rate, "duration_seconds": (count - 1) / rate,
            "latent_frames": (count - 1) // 8, "width": width, "height": height}


def build_command(request, source, destination, info):
    cmd = [str(RUNTIME / ".venv/bin/ltx-2-mlx"), request.operation,
           "--model", str(MODEL), "--video", str(source),
           "--prompt", request.prompt, "--seed", str(request.seed),
           "--low-ram", "--output", str(destination)]
    if request.distilled:
        cmd.append("--distilled")
    if request.operation == "extend":
        cmd += ["--extend-frames", str(request.extend_frames), "--direction", "after"]
    else:
        start = math.floor(request.start_seconds * info["fps"] / 8)
        end = math.ceil(request.end_seconds * info["fps"] / 8)
        if not 0 <= start < end <= info["latent_frames"]:
            raise HTTPException(422, "Retake-Zeitbereich liegt außerhalb des Quellvideos")
        # Keep original speech/audio rather than silently replacing the voice.
        cmd += ["--start", str(start), "--end", str(end), "--no-regen-audio"]
    return cmd


def _runtime_ready():
    cli = RUNTIME / ".venv/bin/ltx-2-mlx"
    if not cli.is_file() or not (MODEL / "embedded_config.json").is_file():
        raise HTTPException(503, "LTX 0.18 oder das lokale Q4-Modell fehlt")
    try:
        sha = subprocess.check_output(["git", "-C", str(RUNTIME), "rev-parse", "HEAD"], text=True, timeout=5).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise HTTPException(503, "LTX 0.18 konnte nicht verifiziert werden") from None
    if sha != EXPECTED_HEAD:
        raise HTTPException(503, "LTX 0.18 hat eine unerwartete Version")
    return True


def _video_idle():
    try:
        with urllib.request.urlopen(VIDEO_HEALTH, timeout=5) as response:
            status = json.load(response)
    except Exception:
        raise HTTPException(503, "Videodienst 8060 nicht erreichbar") from None
    if not status.get("ok") or status.get("status") != "ready" or status.get("active_job_id"):
        raise HTTPException(409, "Ein anderer Videoauftrag läuft bereits")


def _write(job):
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    path = JOB_DIR / f"{job['id']}.json"
    scratch = JOB_DIR / f".{job['id']}.tmp"
    scratch.write_text(json.dumps({k: v for k, v in job.items() if not k.startswith("_")},
                                  ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(scratch, path)


def _update(job_id, **fields):
    with _jlock:
        job = _jobs[job_id]
        if job["status"] in {"completed", "failed", "cancelled"}:
            return
        if job.get("cancel_requested") and fields.get("status") not in {"completed", "failed", "cancelled"}:
            fields.update(phase="cancelling", progress_message="Wird beendet")
        job.update(fields, updated_at=time.time())
        _write(job)


def _chat_loaded():
    return subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{SERVER_LABEL}"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def _chat_command(action):
    done = subprocess.run(["/bin/bash", str(PROJECT / "scripts/mlx"), action],
                          cwd=PROJECT, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=180)
    if done.returncode:
        raise RuntimeError((done.stdout or f"mlx {action} failed")[-2000:])


def _ensure_terminated(job_id, process):
    if process is None:
        return True
    try:
        managed_process.terminate(process)
        return True
    except Exception as exc:
        error = f"Prozessbeendigung nicht bestätigt; KI-Jobannahme gesperrt: {exc}"
        gate.set_blocked(True, error)
        with _jlock:
            job = _jobs[job_id]
            job.update(status="failed", phase="failed", cleanup_failed=True, error=error,
                       finished_at=time.time(), updated_at=time.time())
            _write(job)
        return False


def _run(job_id, request, source, info, cmd, output):
    cancel = _jobs[job_id]["_cancel_event"]
    proc = None
    try:
        _update(job_id, status="preparing", phase="preparing", progress_message="Ressourcen werden vorbereitet", started_at=time.time())
        with runtime_coordinator.video_runtime(
            cancel, chat_loaded=_chat_loaded, chat_command=_chat_command,
            exclusive_models=True,
        ):
            if cancel.is_set():
                raise runtime_coordinator.CoordinationCancelled()
            # Re-check source after the coordinator's potentially lengthy admission.
            source_path(request.source_kind, request.source_id)
            JOB_DIR.mkdir(parents=True, exist_ok=True)
            log = JOB_DIR / f"{job_id}.log"
            _update(job_id, status="generating", phase="generating", progress_message="LTX generiert Videoframes")
            environment = {**os.environ, "PYTHONUNBUFFERED": "1", "TQDM_MININTERVAL": "0.2"}
            parser = ProgressTail(log)
            with log.open("xb", buffering=0) as stream:
                with gate.barrier():
                    gate.check()
                    if cancel.is_set():
                        raise runtime_coordinator.CoordinationCancelled()
                    proc = managed_process.spawn(cmd, owner="video-edit:" + job_id, cwd=RUNTIME, stdout=stream,
                                                 stderr=subprocess.STDOUT, env=environment)
                deadline = time.monotonic() + 7200
                while proc.poll() is None:
                    if cancel.wait(0.2) or gate.blocked():
                        managed_process.terminate(proc)
                        raise runtime_coordinator.CoordinationCancelled()
                    if time.monotonic() > deadline:
                        managed_process.terminate(proc)
                        raise RuntimeError("LTX-Zeitlimit von zwei Stunden erreicht")
                    fields = parser.read()
                    if fields:
                        _update(job_id, **fields)
                    if stream.tell() > 4 * 1024 * 1024:
                        stream.seek(0)
                        stream.truncate()
                        parser.reset()
                fields = parser.read()
                if fields:
                    _update(job_id, **fields)
            managed_process.forget(proc)
            if cancel.is_set() or gate.blocked():
                raise runtime_coordinator.CoordinationCancelled()
            if proc.returncode:
                with log.open("rb") as failed_log:
                    failed_log.seek(max(0, log.stat().st_size - 1500))
                    tail = failed_log.read(1500).decode("utf-8", errors="replace")
                raise RuntimeError(f"LTX {request.operation} fehlgeschlagen: {tail}")
            if not output.is_file() or output.stat().st_size < 32:
                raise RuntimeError("LTX hat kein gültiges MP4 erzeugt")
            with output.open("rb") as generated:
                if b"ftyp" not in generated.read(32):
                    raise RuntimeError("LTX hat kein gültiges MP4 erzeugt")
            # Completion and cancellation share a lock: a confirmed cancel
            # can never be overwritten by a late successful CLI exit.
            with gate.barrier(), _jlock:
                if cancel.is_set() or gate.blocked():
                    raise runtime_coordinator.CoordinationCancelled()
                final_output = output.with_name(f"{job_id}.mp4")
                os.replace(output, final_output)
                media_lifecycle.register("video", job_id, final_output, owner="adhoc", persistent=True)
                _update(job_id, status="completed", phase="completed", progress=1.0,
                        finished_at=time.time(), progress_message="Video gespeichert",
                        result={"id": job_id, "kind": "video", "video_url": f"/api/mlx/videos/{job_id}",
                                "source_kind": request.source_kind, "source_id": request.source_id,
                                "operation": request.operation, "bytes": final_output.stat().st_size})
    except runtime_coordinator.CoordinationCancelled:
        output.unlink(missing_ok=True)
        _update(job_id, status="cancelled", phase="cancelled", finished_at=time.time())
    except Exception as exc:
        if not _ensure_terminated(job_id, proc):
            return
        output.unlink(missing_ok=True)
        _update(job_id, status="cancelled" if cancel.is_set() else "failed",
                error=None if cancel.is_set() else str(exc)[-2000:], finished_at=time.time())
    finally:
        try:
            _ensure_terminated(job_id, proc)
        finally:
            _generation_lock.release()


def _public(job):
    return {k: v for k, v in job.items() if not k.startswith("_")}


def recover_jobs():
    with _jlock:
        for path in JOB_DIR.glob("*.json"):
            if not re.fullmatch(r"[a-f0-9]{24}\.json", path.name):
                continue
            if path.stem in _jobs:
                continue
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(job, dict) or job.get("id") != path.stem:
                    continue
                if job.get("status") in ACTIVE:
                    # Guard pipe EOF handles parent death; reap the persisted
                    # group before declaring an interrupted render terminal.
                    managed_process.stop_all(owner="video-edit:" + job["id"])
                    job.update(status="failed", phase="failed", finished_at=time.time(),
                               updated_at=time.time(), error="Agent wurde während des Edits neu gestartet")
                    (OUTPUT / f"{job['id']}.mp4").unlink(missing_ok=True)
                    (OUTPUT / f".{job['id']}.partial.mp4").unlink(missing_ok=True)
                    _write(job)
                _jobs[job["id"]] = job
            except (OSError, ValueError, TypeError):
                continue


def cancel_all():
    with _jlock:
        for job in _jobs.values():
            if job["status"] in ACTIVE:
                job["_cancel_event"].set()
                _update(job["id"], status="cancelling", phase="cancelling", cancel_requested=True,
                        progress_message="Wird beendet")


def install_routes(app: FastAPI):
    recover_jobs()

    @app.get("/api/video/edit/jobs")
    def list_edits(active_only: bool = True):
        with _jlock:
            return {"jobs": [_public(job) for job in _jobs.values()
                             if not active_only or job.get("status") in ACTIVE]}

    @app.get("/api/video/edit/status")
    def edit_status(source_kind: str = "video", source_id: str = ""):
        _runtime_ready()
        source = source_path(source_kind, source_id)
        return {"ready": True, "source": probe(source),
                "modes": ["extend", "retake"], "runtime": "ltx-mlx-0.18.0"}

    @app.post("/api/video/edit/jobs", status_code=202)
    @gate.admitted
    def create_edit(request: EditRequest):
        _runtime_ready()
        source = source_path(request.source_kind, request.source_id)
        info = probe(source)
        dest = OUTPUT / ("pending.mp4")
        cmd = build_command(request, source, dest, info)  # Validate before acquiring the slot.
        _video_idle()
        if not _generation_lock.acquire(blocking=False):
            raise HTTPException(409, "Ein LTX-Edit läuft bereits")
        try:
            job_id = secrets.token_hex(12)
            OUTPUT.mkdir(parents=True, exist_ok=True)
            # The library scans canonical filenames. Publish atomically only
            # after successful CLI exit and a final cancellation check.
            dest = OUTPUT / f".{job_id}.partial.mp4"
            cmd[cmd.index("--output") + 1] = str(dest)
            job = {"id": job_id, "operation": request.operation, "source_kind": request.source_kind,
                   "source_id": request.source_id, "status": "queued", "phase": "queued", "progress": None,
                   "phase_progress": None, "progress_scope": "phase",
                   "current_step": None, "total_steps": None,
                   "progress_message": "Warte auf LTX", "cancel_requested": False,
                   "updated_at": time.time(), "last_activity_at": None,
                   "error": None, "result": None, "created_at": time.time(),
                   "started_at": None, "finished_at": None,
                   "_cancel_event": threading.Event()}
            with _jlock:
                _jobs[job_id] = job
                _write(job)
            thread = threading.Thread(target=_run, args=(job_id, request, source, info, cmd, dest),
                                      daemon=True, name=f"nobby-ltx-edit-{job_id}")
            thread.start()
            return _public(job)
        except Exception as exc:
            if job_id in _jobs:
                _update(job_id, status="failed", phase="failed", error=str(exc), finished_at=time.time())
            _generation_lock.release()
            raise

    @app.get("/api/video/edit/jobs/{job_id}")
    def edit_job(job_id: str):
        if not re.fullmatch(r"[a-f0-9]{24}", job_id):
            raise HTTPException(422, "Ungültige Edit-ID")
        with _jlock:
            job = _jobs.get(job_id)
            if job is None:
                try:
                    job = json.loads((JOB_DIR / f"{job_id}.json").read_text(encoding="utf-8"))
                    if job.get("status") in ACTIVE:
                        raise HTTPException(503, "Job-Wiederherstellung noch nicht abgeschlossen")
                except (OSError, ValueError):
                    raise HTTPException(404, "Edit-Job nicht gefunden") from None
            return _public(job)

    @app.post("/api/video/edit/jobs/{job_id}/cancel")
    def cancel_edit(job_id: str):
        if not re.fullmatch(r"[a-f0-9]{24}", job_id):
            raise HTTPException(422, "Ungültige Edit-ID")
        with _jlock:
            job = _jobs.get(job_id)
            if job is None:
                raise HTTPException(404, "Edit-Job nicht gefunden")
            if job["status"] not in ACTIVE:
                return _public(job)
            job["_cancel_event"].set()
            _update(job_id, status="cancelling", phase="cancelling", cancel_requested=True,
                    progress_message="Wird beendet")
            return _public(job)
