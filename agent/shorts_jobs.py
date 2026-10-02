"""Persistent, resumable orchestration of ShortProject video scenes."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid

from agent import batch_state, service_proxy, video_api
from agent.shorts_planner import ShortProject


SHORTS_DIRECTORY = Path.home() / ".config/mlx-web/shorts"
SHORTS_JOBS_FILE = SHORTS_DIRECTORY / "jobs.json"
MUSIC_DIRECTORY = Path.home() / ".config/mlx-web/music"
MUSIC_EXTENSIONS = frozenset({".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"})
SHORT_JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{24}$")
ACTIVE_STATUSES = {"queued", "running", "video_completed", "tts_completed"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
VIDEO_ACTIVE_STATUSES = {
    "queued", "dispatching", "loading", "encoding", "generating",
    "upscaling", "decoding", "muxing",
}

_jobs_lock = threading.RLock()
_workers_lock = threading.Lock()
_workers = {}


def _load_jobs():
    return batch_state.load_jobs(SHORTS_JOBS_FILE)


def _save_jobs(jobs):
    batch_state.save_jobs(SHORTS_DIRECTORY, SHORTS_JOBS_FILE, jobs)


def _job_id(value):
    value = str(value or "")
    if not SHORT_JOB_ID_PATTERN.fullmatch(value):
        raise ValueError("invalid short job id")
    return value


def get_short_job(job_id):
    job_id = _job_id(job_id)
    with _jobs_lock:
        job = _load_jobs().get(job_id)
    if job is None:
        raise KeyError("short job not found")
    return deepcopy(job)


def create_short_job(project, *, chat_id, run_id=None, chat_revision=0):
    if not isinstance(project, ShortProject):
        project = ShortProject.model_validate(project)
    if not isinstance(chat_id, str) or not chat_id.strip():
        raise ValueError("chat_id is required")
    if isinstance(chat_revision, bool) or not isinstance(chat_revision, int) or chat_revision < 0:
        raise ValueError("chat_revision must be a non-negative integer")

    job_id = uuid.uuid4().hex[:24]
    job = {
        "id": job_id,
        "kind": "shorts",
        "chat_id": chat_id,
        "run_id": str(run_id or uuid.uuid4().hex),
        "chat_revision": chat_revision,
        "status": "queued",
        "phase": "queued",
        "project": project.model_dump(mode="json"),
        "current_scene": 0,
        "scene_results": [],
        "active_video_job_id": None,
        "tts_status": "pending",
        "tts_path": None,
        "tts_started_at": None,
        "tts_finished_at": None,
        "tts_metadata": None,
        "music_status": "pending" if project.music_enabled else "disabled",
        "music_style": project.music_style or "cinematic",
        "music_path": None,
        "subtitles_path": None,
        "compose_status": "pending",
        "final_path": None,
        "compose_started_at": None,
        "compose_finished_at": None,
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "error": None,
        "cancel_requested": False,
    }
    with _jobs_lock:
        jobs = _load_jobs()
        jobs[job_id] = job
        _save_jobs(jobs)
    return deepcopy(job)


def _update_job(job_id, **changes):
    with _jobs_lock:
        jobs = _load_jobs()
        job = jobs.get(job_id)
        if job is None:
            raise KeyError("short job not found")
        if job.get("status") in TERMINAL_STATUSES:
            return deepcopy(job)
        if changes.get('status') == 'failed':
            from agent.shorts_diagnostics import failure_fields
            fields = failure_fields(job, changes.get('error', ''))
            fields.update({k: v for k, v in changes.items() if k.startswith('error_')})
            changes.update(fields)
        job.update(changes)
        jobs[job_id] = job
        _save_jobs(jobs)
        return deepcopy(job)


def _video_request(request_fn, method, path, payload=None, timeout=15):
    return request_fn(method, path, payload, timeout=timeout)


def _request_tts(payload):
    url = os.environ.get(
        "SPEECH_SERVICE_URL", "http://127.0.0.1:8050",
    ).rstrip("/") + "/v1/audio/speech"
    response = service_proxy.forward(
        url,
        json.dumps(payload).encode("utf-8"),
        timeout=900,
    )
    if response.status_code >= 400:
        detail = bytes(response.body or b"").decode(
            "utf-8", errors="replace",
        )
        raise RuntimeError(detail[:2000] or "speech service failed")
    audio = bytes(response.body or b"")
    if not audio:
        raise RuntimeError("speech service returned empty audio")
    return audio


def narration_for_project(project):
    if not isinstance(project, ShortProject):
        project = ShortProject.model_validate(project)
    return "\n\n".join(scene.narration for scene in project.scenes if scene.voice_enabled and scene.narration)


def tts_payload_for_project(project):
    """Build the speech request while preserving legacy service defaults."""
    if not isinstance(project, ShortProject):
        project = ShortProject.model_validate(project)
    payload = {
        "input": narration_for_project(project),
        "language": project.language,
    }
    if project.voice:
        payload["voice"] = project.voice
    if project.voice_speed != 1.0:
        payload["speed"] = project.voice_speed
    return payload


def _tts_metadata(project, narration):
    metadata = {
        "mime_type": "audio/mpeg",
        "language": project.language,
        "scene_count": len(project.scenes),
        "narration_characters": len(narration),
    }
    if project.voice:
        metadata["voice"] = project.voice
    if project.voice_speed != 1.0:
        metadata["speed"] = project.voice_speed
    return metadata


def _tts_output_path(job_id):
    return SHORTS_DIRECTORY / job_id / "voiceover.mp3"


def _subtitles_output_path(job_id):
    return SHORTS_DIRECTORY / job_id / "subtitles.ass"


def _final_output_path(job_id):
    return SHORTS_DIRECTORY / job_id / "final.mp4"


def _ass_timestamp(seconds):
    centiseconds = round(float(seconds) * 100)
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"


def _ass_text(value):
    return str(value).replace("\\", r"\\").replace("{", r"\{").replace(
        "}", r"\}",
    ).replace("\r\n", r"\N").replace("\r", r"\N").replace("\n", r"\N")


def subtitles_for_project(project):
    if not isinstance(project, ShortProject):
        project = ShortProject.model_validate(project)
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 576
PlayResY: 1024
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,54,&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,42,42,140,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    alignment = {"bottom": 2, "center": 5, "top": 8}[project.captions.position]
    header = header.replace("Arial,54,", f"Arial,{project.captions.size},")
    header = header.replace(",1,3,1,2,42,42,140,1", f",1,3,1,{alignment},42,42,140,1")
    if project.captions.style == "plain":
        header = header.replace(",-1,0,0,0,", ",0,0,0,0,")
    events = []
    start = 0
    for scene in project.scenes:
        end = start + scene.duration
        events.append(
            "Dialogue: 0,"
            f"{_ass_timestamp(start)},{_ass_timestamp(end)},"
            f"Default,,0,0,0,,{_ass_text(scene.caption)}"
        )
        start = end
    return header + "\n".join(events) + "\n"


class _ComposeCancelled(RuntimeError):
    pass


def _run_ffmpeg(command, *, cwd, cancel_check, timeout):
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + timeout
    while True:
        if cancel_check():
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            raise _ComposeCancelled("short job was cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            process.kill()
            _, stderr = process.communicate()
            raise RuntimeError("FFmpeg timed out: " + (stderr or "")[-2000:])
        try:
            _, stderr = process.communicate(timeout=min(0.2, remaining))
            break
        except subprocess.TimeoutExpired:
            continue
    if process.returncode != 0:
        raise RuntimeError("FFmpeg failed: " + (stderr or "")[-2000:])


def _ffmpeg_path():
    return os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg") or "ffmpeg"


def _validated_music_path(path, style):
    candidate = Path(path).expanduser().resolve()
    root = MUSIC_DIRECTORY.expanduser().resolve()
    style_directory = (root / style).resolve()
    if (
        style_directory.parent != root
        or candidate.parent != style_directory
        or candidate.suffix.lower() not in MUSIC_EXTENSIONS
        or not candidate.is_file()
    ):
        raise ValueError("music track must be a supported file inside the music library")
    return candidate


def _select_music_track(job_id, job):
    project = ShortProject.model_validate(job["project"])
    style = project.music_style or "cinematic"
    if not project.music_enabled:
        return "disabled", style, None

    persisted = job.get("music_path")
    if persisted:
        try:
            return "selected", style, _validated_music_path(persisted, style)
        except ValueError:
            return "missing", style, None

    root = MUSIC_DIRECTORY.expanduser().resolve()
    style_directory = (root / style).resolve()
    if style_directory.parent != root or not style_directory.is_dir():
        return "missing", style, None
    try:
        candidates = list(style_directory.iterdir())
    except OSError:
        return "missing", style, None
    tracks = []
    for candidate in candidates:
        try:
            tracks.append(_validated_music_path(candidate, style))
        except ValueError:
            continue
    if not tracks:
        return "missing", style, None
    tracks.sort(key=lambda candidate: (candidate.name.casefold(), str(candidate)))
    digest = hashlib.sha256(f"{job_id}:{style}".encode("utf-8")).digest()
    index = int.from_bytes(digest[:8], "big") % len(tracks)
    return "selected", style, tracks[index]


def _compose_command(job, output_path):
    project = ShortProject.model_validate(job["project"])
    if project.schema_version == 2:
        from agent.shorts_composer import compose_command
        return compose_command(job, output_path)
    from agent.shorts_planner import quality_capabilities
    width, height = quality_capabilities()[project.quality]["dimensions"]
    results = {
        result["scene_id"]: result
        for result in job.get("scene_results", [])
        if result.get("status") == "completed"
    }
    command = [_ffmpeg_path(), "-y", "-nostdin", "-loglevel", "error"]
    filters = []
    video_labels = []
    for index, scene in enumerate(project.scenes):
        result = results.get(scene.id)
        if not result or not result.get("path"):
            raise RuntimeError(f"completed video missing for scene {scene.id}")
        command.extend(["-i", str(result["path"])])
        label = f"v{index}"
        filters.append(
            f"[{index}:v:0]"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:"
            "force_divisible_by=2,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fps=30,setsar=1,tpad=stop_mode=clone:stop_duration={scene.duration},"
            f"trim=duration={scene.duration},"
            f"setpts=PTS-STARTPTS[{label}]"
        )
        video_labels.append(f"[{label}]")

    audio_index = len(project.scenes)
    if project.voice_enabled and narration_for_project(project):
        tts_path = str(job.get("tts_path") or "")
        if not tts_path:
            raise RuntimeError("completed TTS has no audio path")
        command.extend(["-i", tts_path])
    else:
        command.extend([
            "-f", "lavfi", "-t", str(project.duration),
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        ])

    music_path = job.get("music_path") if project.music_enabled else None
    music_index = None
    if music_path:
        music_path = _validated_music_path(music_path, job.get("music_style") or "cinematic")
        music_index = audio_index + 1
        command.extend(["-stream_loop", "-1", "-i", str(music_path)])

    filters.append(
        "".join(video_labels)
        + f"concat=n={len(video_labels)}:v=1:a=0[joined]"
    )
    video_output = "joined"
    if project.subtitles_enabled:
        filters.append("[joined]ass=subtitles.ass[subtitled]")
        video_output = "subtitled"

    audio_output = f"{audio_index}:a:0"
    if music_index is not None:
        fade_duration = min(2, project.duration)
        fade_start = max(0, project.duration - fade_duration)
        filters.extend([
            f"[{audio_index}:a:0]aresample=48000,apad,"
            f"atrim=duration={project.duration},asplit=2[voice_mix][voice_key]",
            f"[{music_index}:a:0]aresample=48000,volume=0.18,"
            f"afade=t=out:st={fade_start}:d={fade_duration},"
            f"atrim=duration={project.duration}[music]",
            "[music][voice_key]sidechaincompress="
            "threshold=0.03:ratio=10:attack=20:release=400[ducked]",
            "[voice_mix][ducked]amix=inputs=2:duration=first:"
            "dropout_transition=0[audio]",
        ])
        audio_output = "[audio]"

    command.extend([
        "-filter_complex", ";".join(filters),
        "-map", f"[{video_output}]",
        "-map", audio_output,
        "-t", str(project.duration),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", "-f", "mp4", str(output_path),
    ])
    return command


def _retryable_service_error(exc, *status_codes):
    return getattr(exc, "status_code", None) in status_codes


def _scene_request(job, scene):
    return {
        "operation": "t2v",
        "payload": {
            "prompt": scene["video_prompt"] + ("\nCamera: " + scene["camera"] if scene.get("camera") else ""),
            "duration": scene["duration"],
            "aspect_ratio": job["project"]["aspect_ratio"],
            # Fast supports every duration accepted by ShortProject.
            "quality": job["project"].get("quality", "fast"),
        },
        "chat_id": job["chat_id"],
        "run_id": job["run_id"],
        "chat_revision": job["chat_revision"],
    }


def valid_media_file(path):
    """Cheap reuse check shared by revisions and resource preflight."""
    if not path:
        return False
    try:
        file = Path(path)
        return file.is_file() and file.stat().st_size > 0
    except (OSError, TypeError, ValueError):
        return False


def _completed_scene_ids(job):
    return {
        result.get("scene_id")
        for result in job.get("scene_results", [])
        if result.get("status") == "completed"
    }


def _cancel_active_video(job, request_fn):
    child_id = job.get("active_video_job_id")
    if not child_id:
        return
    try:
        _video_request(
            request_fn,
            "POST",
            "/jobs/" + video_api.job_id(child_id) + "/cancel",
            {},
            timeout=30,
        )
    except Exception:
        # Best effort: the durable parent state still prevents consumption.
        pass


def _finish_cancelled(job_id, request_fn):
    job = get_short_job(job_id)
    if job.get('active_image_job_id'):
        from agent import image_api
        try:
            image_api.request('POST', '/jobs/' + image_api.job_id(job['active_image_job_id']) + '/cancel', {}, timeout=30)
        except Exception:
            pass
    _cancel_active_video(job, request_fn)
    with _jobs_lock:
        jobs = _load_jobs()
        job = jobs.get(job_id)
        if job is None:
            raise KeyError("short job not found")
        if job.get("status") == "completed":
            return deepcopy(job)
        compose_was_started = job.get("compose_status") == "running"
        job.update(
            cancel_requested=True,
            active_image_job_id=None,
            active_video_job_id=None,
            status="cancelled",
            phase="cancelled",
            tts_status=(
                "cancelled"
                if job.get("tts_status") != "completed"
                else "completed"
            ),
            tts_finished_at=(
                job.get("tts_finished_at") or time.time()
            ),
            compose_status=(
                "cancelled" if compose_was_started else job.get("compose_status", "pending")
            ),
            compose_finished_at=(
                time.time() if compose_was_started else job.get("compose_finished_at")
            ),
            finished_at=time.time(),
            error=None,
        )
        jobs[job_id] = job
        _save_jobs(jobs)
        return deepcopy(job)


def _run_tts(job_id, request_fn, tts_request_fn):
    job = get_short_job(job_id)
    if job.get("cancel_requested"):
        return _finish_cancelled(job_id, request_fn)

    existing_path = Path(str(job.get("tts_path") or _tts_output_path(job_id)))
    if existing_path.is_file() and existing_path.stat().st_size > 0:
        project = ShortProject.model_validate(job["project"])
        narration = narration_for_project(project)
        finished_at = job.get("tts_finished_at") or time.time()
        return _update_job(
            job_id,
            status="tts_completed",
            phase="tts_completed",
            tts_status="completed",
            tts_path=str(existing_path),
            tts_finished_at=finished_at,
            tts_metadata=job.get("tts_metadata") or _tts_metadata(project, narration),
            finished_at=job.get("finished_at") or finished_at,
            error=None,
        )

    project = ShortProject.model_validate(job["project"])
    if not project.voice_enabled or not narration_for_project(project):
        now = time.time()
        return _update_job(
            job_id,
            status="tts_completed",
            phase="tts_completed",
            tts_status="disabled",
            tts_finished_at=now,
            tts_metadata={
                "language": project.language,
                "scene_count": len(project.scenes),
                "disabled": True,
            },
            finished_at=now,
            error=None,
        )

    started_at = job.get("tts_started_at") or time.time()
    _update_job(
        job_id,
        status="running",
        phase="tts",
        tts_status="running",
        tts_started_at=started_at,
        error=None,
    )
    narration = narration_for_project(project)
    if project.schema_version == 2:
        from agent.shorts_composer import scene_tts
        audio = scene_tts(job_id, project, tts_request_fn)
    else:
        audio = tts_request_fn(tts_payload_for_project(project))
    if not isinstance(audio, bytes) or not audio:
        raise RuntimeError("speech service returned invalid audio")

    if get_short_job(job_id).get("cancel_requested"):
        return _finish_cancelled(job_id, request_fn)

    output_path = _tts_output_path(job_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    batch_state.atomic_write_with(
        output_path,
        lambda temporary: temporary.write_bytes(audio),
    )

    if get_short_job(job_id).get("cancel_requested"):
        output_path.unlink(missing_ok=True)
        return _finish_cancelled(job_id, request_fn)

    finished_at = time.time()
    return _update_job(
        job_id,
        status="tts_completed",
        phase="tts_completed",
        tts_status="completed",
        tts_path=str(output_path),
        tts_finished_at=finished_at,
        tts_metadata=_tts_metadata(project, narration),
        finished_at=finished_at,
        error=None,
    )


def _run_compose(job_id, request_fn, compose_fn):
    job = get_short_job(job_id)
    if job.get("cancel_requested"):
        return _finish_cancelled(job_id, request_fn)

    output_path = _final_output_path(job_id)
    persisted_output = Path(str(job.get("final_path") or output_path))
    if persisted_output.is_file() and persisted_output.stat().st_size > 0:
        finished_at = job.get("compose_finished_at") or time.time()
        return _update_job(
            job_id,
            status="completed",
            phase="completed",
            compose_status="completed",
            final_path=str(persisted_output),
            compose_finished_at=finished_at,
            finished_at=finished_at,
            error=None,
        )

    project = ShortProject.model_validate(job["project"])
    if project.schema_version == 2:
        from agent.shorts_composer import scene_music, select_track
        selections = [{"scene_id": scene.id, "path": str(path) if path else None}
                      for scene in project.scenes
                      for path in [select_track(MUSIC_DIRECTORY, scene_music(project, scene))]]
        music_status = "selected" if any(item["path"] for item in selections) else "disabled"
        music_style = project.music_style or "cinematic"
        music_path = None
        _update_job(job_id, scene_music_results=selections)
    else:
        music_status, music_style, music_path = _select_music_track(job_id, job)
    job = _update_job(
        job_id,
        music_status=music_status,
        music_style=music_style,
        music_path=str(music_path) if music_path else None,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subtitles_path = _subtitles_output_path(job_id)
    if project.subtitles_enabled:
        batch_state.atomic_write_text(
            subtitles_path,
            subtitles_for_project(project),
        )

    started_at = job.get("compose_started_at") or time.time()
    job = _update_job(
        job_id,
        status="running",
        phase="compose",
        subtitles_path=str(subtitles_path) if project.subtitles_enabled else None,
        compose_status="running",
        compose_started_at=started_at,
        finished_at=None,
        error=None,
    )
    if job.get("cancel_requested"):
        return _finish_cancelled(job_id, request_fn)

    def render(temporary_path):
        command = _compose_command(job, temporary_path)
        compose_fn(
            command,
            cwd=output_path.parent,
            cancel_check=lambda: get_short_job(job_id).get("cancel_requested", False),
            timeout=1800,
        )
        if not temporary_path.is_file() or temporary_path.stat().st_size <= 0:
            raise RuntimeError("FFmpeg did not create a final MP4")

    try:
        batch_state.atomic_write_with(output_path, render)
    except _ComposeCancelled:
        return _finish_cancelled(job_id, request_fn)

    if get_short_job(job_id).get("cancel_requested"):
        output_path.unlink(missing_ok=True)
        return _finish_cancelled(job_id, request_fn)

    finished_at = time.time()
    return _update_job(
        job_id,
        status="completed",
        phase="completed",
        compose_status="completed",
        final_path=str(output_path),
        compose_finished_at=finished_at,
        finished_at=finished_at,
        error=None,
    )


def _run_after_video(job_id, request_fn, tts_request_fn, compose_fn):
    job = get_short_job(job_id)
    if job.get("status") == "video_completed":
        job = _run_tts(job_id, request_fn, tts_request_fn)
    if job.get("status") == "tts_completed":
        return _run_compose(job_id, request_fn, compose_fn)
    return job


def run_short_job(
    job_id,
    *,
    request_fn=None,
    tts_request_fn=None,
    compose_fn=None,
    poll_interval=1.0,
):
    """Run or resume one job synchronously; workers call this in a thread."""
    job_id = _job_id(job_id)
    request_fn = request_fn or video_api.request
    tts_request_fn = tts_request_fn or _request_tts
    compose_fn = compose_fn or _run_ffmpeg
    job = get_short_job(job_id)
    if job.get("status") in TERMINAL_STATUSES:
        return job
    if job.get("cancel_requested"):
        return _finish_cancelled(job_id, request_fn)

    if job.get("status") in {"video_completed", "tts_completed"}:
        try:
            return _run_after_video(
                job_id, request_fn, tts_request_fn, compose_fn,
            )
        except Exception as exc:
            latest = get_short_job(job_id)
            if latest.get("cancel_requested"):
                return _finish_cancelled(job_id, request_fn)
            changes = {
                "status": "failed",
                "phase": "failed",
                "error": str(exc),
                "finished_at": time.time(),
            }
            if latest.get("phase") == "compose":
                changes.update(
                    compose_status="failed",
                    compose_finished_at=time.time(),
                )
            else:
                changes.update(
                    tts_status="failed",
                    tts_finished_at=time.time(),
                )
            from agent.shorts_diagnostics import failure_fields
            changes.update(failure_fields(latest, exc))
            return _update_job(job_id, **changes)

    _update_job(
        job_id,
        status="running",
        phase="video",
        started_at=job.get("started_at") or time.time(),
        error=None,
    )

    try:
        while True:
            job = get_short_job(job_id)
            if job.get("status") in TERMINAL_STATUSES:
                return job
            if job.get("cancel_requested"):
                return _finish_cancelled(job_id, request_fn)

            project = ShortProject.model_validate(job["project"])
            completed_ids = _completed_scene_ids(job)
            scene_index = 0
            while (
                scene_index < len(project.scenes)
                and project.scenes[scene_index].id in completed_ids
            ):
                scene_index += 1

            if scene_index >= len(project.scenes):
                _update_job(
                    job_id,
                    status="video_completed",
                    phase="video_completed",
                    current_scene=len(project.scenes),
                    active_video_job_id=None,
                    finished_at=None,
                    error=None,
                )
                return _run_after_video(
                    job_id, request_fn, tts_request_fn, compose_fn,
                )

            if scene_index != job.get("current_scene"):
                job = _update_job(job_id, current_scene=scene_index)

            scene = project.scenes[scene_index].model_dump(mode="json")
            child_id = job.get("active_video_job_id")
            if not child_id:
                try:
                    child = _video_request(
                        request_fn,
                        "POST",
                        "/jobs",
                        _scene_request(job, scene),
                        timeout=15,
                    )
                except Exception as exc:
                    if _retryable_service_error(exc, 409, 503):
                        time.sleep(max(poll_interval, 0.1))
                        continue
                    raise
                child_id = video_api.job_id(child.get("id"))
                job = _update_job(
                    job_id,
                    active_video_job_id=child_id,
                    phase="video",
                )

            try:
                child = _video_request(
                    request_fn,
                    "GET",
                    "/jobs/" + video_api.job_id(child_id),
                    timeout=15,
                )
            except Exception as exc:
                if _retryable_service_error(exc, 503):
                    time.sleep(max(poll_interval, 0.1))
                    continue
                raise
            status = str(child.get("status") or "")
            if get_short_job(job_id).get("cancel_requested"):
                return _finish_cancelled(job_id, request_fn)

            if status == "completed":
                result = child.get("result") or {}
                path = str(result.get("path") or "")
                if not path.endswith(".mp4"):
                    raise RuntimeError("completed video job has no MP4 path")

                latest = get_short_job(job_id)
                if latest.get("cancel_requested"):
                    return _finish_cancelled(job_id, request_fn)
                results = list(latest.get("scene_results") or [])
                if scene["id"] not in _completed_scene_ids(latest):
                    results.append({
                        "scene_id": scene["id"],
                        "duration": scene["duration"],
                        "status": "completed",
                        "video_job_id": child_id,
                        "path": path,
                    })
                _update_job(
                    job_id,
                    current_scene=scene_index + 1,
                    scene_results=results,
                    active_video_job_id=None,
                )
                continue

            if status == "failed":
                return _update_job(
                    job_id,
                    status="failed",
                    phase="failed",
                    error=str(child.get("error") or "video job failed"),
                    finished_at=time.time(),
                )

            if status == "cancelled":
                latest = get_short_job(job_id)
                if latest.get("cancel_requested"):
                    return _finish_cancelled(job_id, request_fn)
                return _update_job(
                    job_id,
                    status="failed",
                    phase="failed",
                    error="video job was cancelled unexpectedly",
                    finished_at=time.time(),
                )

            if status not in VIDEO_ACTIVE_STATUSES:
                raise RuntimeError(f"unknown video job status: {status or 'empty'}")

            if poll_interval:
                time.sleep(poll_interval)

    except Exception as exc:
        latest = get_short_job(job_id)
        if latest.get("cancel_requested"):
            return _finish_cancelled(job_id, request_fn)
        changes = {
            "status": "failed",
            "phase": "failed",
            "error": str(exc),
            "finished_at": time.time(),
        }
        if get_short_job(job_id).get("phase") == "tts":
            changes.update(
                tts_status="failed",
                tts_finished_at=time.time(),
            )
        elif get_short_job(job_id).get("phase") == "compose":
            changes.update(
                compose_status="failed",
                compose_finished_at=time.time(),
            )
        from agent.shorts_diagnostics import failure_fields
        changes.update(failure_fields(latest, exc))
        return _update_job(
            job_id,
            **changes,
        )


def _worker(job_id, request_fn, tts_request_fn, compose_fn, poll_interval):
    try:
        run_short_job(
            job_id,
            request_fn=request_fn,
            tts_request_fn=tts_request_fn,
            compose_fn=compose_fn,
            poll_interval=poll_interval,
        )
    finally:
        with _workers_lock:
            current = _workers.get(job_id)
            if current is threading.current_thread():
                _workers.pop(job_id, None)


def start_short_job(
    job_id,
    *,
    request_fn=None,
    tts_request_fn=None,
    compose_fn=None,
    poll_interval=1.0,
):
    job_id = _job_id(job_id)
    job = get_short_job(job_id)
    if job.get("status") in TERMINAL_STATUSES:
        return job
    with _workers_lock:
        worker = _workers.get(job_id)
        if worker is not None and worker.is_alive():
            return job
        worker = threading.Thread(
            target=_worker,
            args=(job_id, request_fn, tts_request_fn, compose_fn, poll_interval),
            daemon=True,
            name=f"mlx-short-{job_id[:8]}",
        )
        _workers[job_id] = worker
        worker.start()
    return get_short_job(job_id)


def cancel_short_job(job_id, request_fn=None):
    job_id = _job_id(job_id)
    request_fn = request_fn or video_api.request
    job = get_short_job(job_id)
    if job.get("status") in TERMINAL_STATUSES:
        raise ValueError("short job is already finished")
    _update_job(job_id, cancel_requested=True)
    return _finish_cancelled(job_id, request_fn)


def cancel_chat_jobs(chat_id):
    with _jobs_lock:
        ids = [job_id for job_id, job in _load_jobs().items()
               if job.get("chat_id") == chat_id and job.get("status") in ACTIVE_STATUSES]
    cancelled = []
    for job_id in ids:
        try:
            cancel_short_job(job_id)
            cancelled.append(job_id)
        except ValueError:
            # A worker may have completed between the snapshot and cancellation.
            if get_short_job(job_id).get("status") not in TERMINAL_STATUSES:
                raise
    return cancelled


def resume_short_jobs():
    with _jobs_lock:
        jobs = _load_jobs()
        resumable = [
            job_id
            for job_id, job in jobs.items()
            if job.get("status") in ACTIVE_STATUSES
            and not job.get("cancel_requested")
        ]
    for job_id in resumable:
        start_short_job(job_id)
    return resumable
