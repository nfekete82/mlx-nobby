"""Sequential LTX temporal extension inside the native video job's ONE lease.

No service-to-service jobs, concatenation, second scheduler or model downloads.
The checkpoint is the full accumulated clip returned by LTX, not a new scene.
"""
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

import ai_lifecycle_gate as gate
import managed_process
import runtime_coordinator as coordinator
import video_registry
from ltx_progress import ProgressTail
from video_providers import ProviderCancelled

RUNTIME = Path.home() / ".local/share/mlx-nobby/ltx-2-mlx-v0.18.0"
EXPECTED_HEAD = "b82b97e3d000e01361f8cfcb745244b15b89a521"
FPS = 24
TEMPORAL_STRIDE = 8
MAX_EXTEND_LATENTS = 12
DIRECT = {"preview": (2,), "540p": (5, 6, 8, 10, 20), "720p": (5, 6, 8, 10), "1080p": (5,)}
SUPPORTED = {key: tuple(sorted(set(values) | ({10, 20, 30, 60} if key != "preview" else set())
                                   | ({9} if key == "1080p" else set())))
             for key, values in DIRECT.items()}


def plan(duration, resolution, fps=FPS):
    if resolution not in DIRECT or duration not in SUPPORTED[resolution]:
        raise ValueError("Nicht unterstützte Videolänge; automatische Fortsetzung unterstützt bis zu 60 Sekunden")
    initial = max(value for value in DIRECT[resolution] if value <= duration)
    if duration == initial:
        return {"duration": duration, "resolution": resolution, "fps": fps, "frames": duration * fps + 1,
                "initial_seconds": initial, "stages": [{"frames": duration * fps + 1, "extend_latents": 0}]}
    if fps != FPS or (duration * fps) % TEMPORAL_STRIDE:
        raise ValueError("Automatische Fortsetzung benötigt 24 fps und 8k+1 Frames")
    remaining = (duration - initial) * fps // TEMPORAL_STRIDE
    frames = initial * fps + 1
    stages = [{"frames": frames, "extend_latents": 0}]
    while remaining:
        amount = min(MAX_EXTEND_LATENTS, remaining)
        frames += TEMPORAL_STRIDE * amount
        stages.append({"frames": frames, "extend_latents": amount})
        remaining -= amount
    return {"duration": duration, "resolution": resolution, "fps": fps, "frames": frames, "initial_seconds": initial, "stages": stages}


def needed(params):
    return len(plan(params["duration"], params["resolution"], params["fps"])["stages"]) > 1


def runtime_version():
    cli = RUNTIME / ".venv/bin/ltx-2-mlx"
    if not cli.is_file():
        raise RuntimeError("Automatische Fortsetzung benötigt die installierte LTX-MLX-0.18-CLI")
    head = subprocess.check_output(["git", "-C", str(RUNTIME), "rev-parse", "HEAD"], text=True, timeout=5).strip()
    if head != EXPECTED_HEAD:
        raise RuntimeError("LTX-Extend-Version weicht vom geprüften 0.18-Checkout ab")
    return head


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def capture(command, cancel=None, timeout=120):
    """Bounded CPU probes stay cancellable too; stderr is never a public prompt log."""
    process = managed_process.spawn(command, owner="video:long:probe", stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + timeout
    try:
        while True:
            _check(cancel or threading.Event())
            if time.monotonic() > deadline:
                raise RuntimeError("Video-Prüfung hat ihr Zeitlimit überschritten")
            try:
                output, error = process.communicate(timeout=0.2)
                if process.returncode:
                    raise RuntimeError(f"Video-Prüfung fehlgeschlagen (Exit {process.returncode})")
                return output
            except subprocess.TimeoutExpired:
                continue
    finally:
        managed_process.terminate(process)


def boundary_check(path, previous_frames, cancel):
    output = capture(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf",
                      f"select=eq(n\\,{previous_frames-1})+eq(n\\,{previous_frames})",
                      "-fps_mode", "passthrough", "-frames:v", "2", "-f", "framemd5", "-"], cancel)
    hashes = [row.rsplit(",", 1)[-1].strip() for row in output.splitlines() if row and not row.startswith("#")]
    if len(hashes) != 2:
        raise RuntimeError("Übergangsframes konnten nicht verifiziert werden")
    return {"boundary_frames_checked": 2, "identical_boundary_pixels": hashes[0] == hashes[1],
            "perceptual_continuity": "requires_review"}


def validate(path, stage, params, cancel=None):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Video-Checkpoint fehlt oder ist ein Symlink")
    output = capture(["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format",
                      "-of", "json", str(path)], cancel)
    streams = json.loads(output)["streams"]
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) > 1:
        raise RuntimeError("Checkpoint benötigt genau eine Videospur und höchstens eine Audiospur")
    video = videos[0]
    frames = int(video.get("nb_read_frames") or video.get("nb_frames") or 0)
    fps = Fraction(video["avg_frame_rate"])
    expected_seconds = stage["frames"] / params["fps"]
    seconds = float(video.get("duration") or json.loads(output)["format"]["duration"])
    if (frames != stage["frames"] or frames % TEMPORAL_STRIDE != 1 or fps != params["fps"]
            or (int(video["width"]), int(video["height"])) != (params["width"], params["height"])
            or abs(seconds - expected_seconds) > 0.5 / params["fps"]):
        raise RuntimeError(f"LTX-Checkpoint inkonsistent: erwartet {stage['frames']} Frames bei {params['fps']} fps und unveränderter Auflösung")
    if audios and abs(float(audios[0].get("duration") or seconds) - seconds) > 0.15:
        raise RuntimeError("LTX-Checkpoint hat inkonsistente Audio-/Videodauer")
    return {"frames": frames, "fps": float(fps), "width": int(video["width"]), "height": int(video["height"]),
            "duration": seconds, "timeline_seconds": (frames - 1) / float(fps), "audio": bool(audios),
            "audio_signature": {key: audios[0].get(key) for key in ("sample_rate", "channels")} if audios else None}


def _check(cancel):
    if cancel.is_set() or gate.blocked():
        raise ProviderCancelled("Long video was cancelled")


def extend(source, destination, amount, params, cancel, update, owner):
    command = [str(RUNTIME / ".venv/bin/ltx-2-mlx"), "extend", "--distilled", "--low-ram",
               "--model", str(params["model_path"]), "--video", str(source), "--prompt", params["prompt"],
               "--extend-frames", str(amount), "--direction", "after", "--seed", str(params["seed"]),
               "--output", str(destination)]
    log = destination.with_suffix(".log")
    reader = ProgressTail(log)
    process = None
    baseline = coordinator.memory_budget_snapshot()
    coordinator.ensure_model_load_allowed("video", snapshot=baseline)
    coordinator.ensure_active_memory_safe(baseline)
    try:
        with log.open("wb", buffering=0) as stream:
            process = managed_process.spawn(command, owner=owner, cwd=RUNTIME, stdout=stream,
                                            stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUNBUFFERED": "1"})
            deadline, sample_at = time.monotonic() + 7200, time.monotonic()
            while process.poll() is None:
                _check(cancel)
                if time.monotonic() > deadline:
                    raise RuntimeError("LTX-Extend-Zeitlimit erreicht")
                if time.monotonic() - sample_at >= 2:
                    coordinator.ensure_active_memory_safe(coordinator.memory_budget_snapshot(), baseline_swap_gb=baseline.get("swap_used_gb"))
                    sample_at = time.monotonic()
                fields = reader.read()
                if fields:
                    fields.pop("progress", None)
                    update(**fields)
                if stream.tell() > 4 * 1024 * 1024:
                    stream.seek(0); stream.truncate(); reader.reset()
                cancel.wait(0.2)
        _check(cancel)
        if process.returncode:
            # CLI logs may contain prompts. Keep public errors content-free.
            raise RuntimeError(f"LTX-Extend fehlgeschlagen (Exit {process.returncode}); lokales Stufenlog verfügbar")
    finally:
        if process is not None:
            try:
                managed_process.terminate(process)
            except Exception:
                gate.set_blocked(True, "LTX-Extend-Cleanup nicht verifiziert")
                raise
        if process is None or process.returncode != 0:
            destination.unlink(missing_ok=True)


def run(model, params, output, *, job_id, checkpoints, resume_job, generate, cancel_event,
        response_callback, progress_callback, phase_callback, update):
    version = runtime_version()
    if model.get("provider") != "ltx-mlx" or params.get("profile", "standard") != "standard":
        raise ValueError("Automatische Fortsetzung unterstützt derzeit das native Standard-LTX-MLX-Modell")
    if params["width"] % 64 or params["height"] % 64:
        raise ValueError("LTX-Extend benötigt dieselbe Auflösung auf einem 64-Pixel-Raster")
    planner = plan(params["duration"], params["resolution"], params["fps"])
    model_path = video_registry.model_path(model).resolve()
    # Checkpoint identity includes effective options, model installation and CLI version.
    effective = {**params, "model_path": str(model_path)}
    effective.pop("resume_from", None)
    # A default, unused rolling-only option must not invalidate old checkpoints.
    if effective.get("face_guidance") is None:
        effective.pop("face_guidance", None)
    config = model_path / "embedded_config.json"
    identity = {"params": effective, "runtime": version, "model": model["id"],
                "model_config_sha256": digest(config),
                "weights": [{"name": str(path.relative_to(model_path)), "size": path.stat().st_size,
                             "mtime_ns": path.stat().st_mtime_ns} for path in sorted(model_path.rglob("*.safetensors"))],
                "first_frame_sha256": digest(Path(params["first_frame"])) if params.get("first_frame") else None}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    directory = checkpoints / job_id
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "checkpoint.json"
    previous = None
    if resume_job:
        if resume_job.get("status") == "cancelled" or resume_job.get("cancel_requested") and resume_job.get("cancel_reason") != "lifecycle":
            raise ValueError("Expliziter Abbruch wird nicht automatisch fortgesetzt")
        previous = checkpoints / resume_job["id"]
    manifest = {"version": 1, "fingerprint": fingerprint, "identity": identity, "plan": planner, "stages": []}
    atomic_json(manifest_path, manifest)
    if previous:
        saved = json.loads((previous / "checkpoint.json").read_text())
        if saved.get("fingerprint") != fingerprint:
            raise ValueError("Checkpoint-Einstellungen, Modell oder Laufzeit haben sich geändert")
        for entry in saved["stages"]:
            index = len(manifest["stages"])
            source = previous / f"stage-{index}.mp4"
            _check(cancel_event)
            info = validate(source, planner["stages"][index], effective, cancel_event)
            if digest(source) != entry["sha256"]:
                raise ValueError("Video-Checkpoint wurde verändert")
            shutil.copy2(source, directory / source.name)
            manifest["stages"].append(entry)
            atomic_json(manifest_path, manifest)
    atomic_json(manifest_path, manifest)
    update(automatic_continuation=True, long_plan=planner, stage_count=len(planner["stages"]),
           target_duration=params["duration"], continuity_warning="LTX rekodiert den bisherigen Clip; perfekte Bild-/Audiokontinuität ist nicht garantiert.",
           resumable=bool(manifest["stages"]))
    media = {}
    for index, stage in enumerate(planner["stages"]):
        _check(cancel_event)
        confirmed = (manifest["stages"][-1]["info"]["timeline_seconds"] if manifest["stages"] else 0)
        update(stage_number=index + 1, confirmed_duration=confirmed,
               phase_progress=None, current_step=None, total_steps=None, progress=None,
               progress_message="LTX bereitet Videoabschnitt vor", progress_scope=None,
               phase="generating", status="generating", last_activity_at=time.time())
        if index < len(manifest["stages"]):
            continue
        temporary = directory / f"stage-{index}.partial.mp4"
        final = directory / f"stage-{index}.mp4"
        try:
            if index == 0:
                initial = {**params, "duration": planner["initial_seconds"], "frames": stage["frames"], "_truthful_progress": True}
                media = generate(model, initial, temporary, cancel_event=cancel_event,
                                 response_callback=response_callback, progress_callback=progress_callback,
                                 phase_callback=phase_callback)
                # Existing provider intentionally keeps a warm worker. Release
                # it here before a separate 0.18 CLI can load any model.
                from video_providers_mlx import shutdown_warm_runtime
                shutdown_warm_runtime()
            else:
                extend(directory / f"stage-{index-1}.mp4", temporary, stage["extend_latents"], effective,
                       cancel_event, update, "video:long:" + job_id)
            _check(cancel_event)
            info = validate(temporary, stage, effective, cancel_event)
            if index:
                info.update(boundary_check(temporary, planner["stages"][index-1]["frames"], cancel_event))
            if index and info["audio_signature"] != manifest["stages"][index-1]["info"].get("audio_signature"):
                raise RuntimeError("LTX hat das Audioformat zwischen Abschnitten verändert")
            entry = {"index": index, "info": info, "sha256": digest(temporary), "validated_at": time.time()}
            # File first, manifest second: an interrupted rename can never
            # falsely claim a validated checkpoint. Retry reuses only manifest entries.
            with gate.barrier():
                _check(cancel_event)
                os.replace(temporary, final)
                manifest["stages"].append(entry)
                atomic_json(manifest_path, manifest)
            update(confirmed_duration=info["timeline_seconds"], resumable=True,
                   checkpoint_count=len(manifest["stages"]), last_activity_at=time.time(),
                   identical_boundary_pixels=bool(info.get("identical_boundary_pixels")))
        finally:
            temporary.unlink(missing_ok=True)
    _check(cancel_event)
    final_info = validate(directory / f"stage-{len(planner['stages'])-1}.mp4", planner["stages"][-1], effective, cancel_event)
    # The service publishes this private output atomically after its own cancel check.
    shutil.copy2(directory / f"stage-{len(planner['stages'])-1}.mp4", output)
    return {**media, **final_info, "duration": params["duration"], "automatic_continuation": True,
            "stage_count": len(planner["stages"]), "actual_duration": final_info["duration"],
            "continuity_warning": "LTX continuation re-encodes the source; continuity requires visual/audio acceptance."}
