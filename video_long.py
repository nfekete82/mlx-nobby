"""RAM-safe, checkpointed LTX long-video generation (30/60 seconds).

Each short, independent generation runs in the existing video-runtime lease.
The MLX worker is cold-reset between segments to avoid accumulating Metal/
Python allocations. Generated last frames are stored only in managed job
directories; untrusted client paths are never accepted as checkpoint inputs.
"""
from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import runtime_coordinator
from video_providers import FFMPEG, ProviderCancelled, _probe_video
from video_providers_mlx import shutdown_warm_runtime


LONG_DURATIONS = frozenset({30, 60})
# At 1080p even a 5-second native MLX request may exceed 48 GB unified RAM.
SEGMENT_SECONDS = {"1080p": 3, "720p": 5, "540p": 6}


def segment_plan(duration, resolution):
    """Fixed, reproducible plan; all supported durations divide exactly."""
    duration = int(duration)
    if duration not in LONG_DURATIONS or resolution not in SEGMENT_SECONDS:
        raise ValueError("Long-Video benötigt 30/60 s und 540p, 720p oder 1080p")
    length = SEGMENT_SECONDS[resolution]
    if duration % length:
        raise ValueError("Long-Video-Segmente müssen die Dauer genau abdecken")
    return [length] * (duration // length)


def _check_cancel(cancel_event):
    if cancel_event.is_set():
        raise ProviderCancelled("Video job was cancelled")


def _last_frame(video, image):
    """Extract the final decoded frame without keeping the whole clip in RAM."""
    image.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
         "-sseof", "-0.5", "-i", str(video), "-an", "-update", "1", str(image)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0 or not image.is_file() or not image.stat().st_size:
        raise RuntimeError("Letztes Segmentbild konnte nicht extrahiert werden: "
                           + result.stderr[-1000:])


def _concat_segments(paths, output, params):
    """Stream-copy MP4 segments: no simultaneous 1080p re-decode in ffmpeg."""
    baseline = None
    for path in paths:
        info = _probe_video(path)
        current = (info["width"], info["height"], round(info["fps"], 2), bool(info["audio"]))
        if baseline is None:
            baseline = current
        elif current != baseline:
            raise RuntimeError("LTX-Segmente besitzen unterschiedliche Audio-/Videostreams")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mlx-long-concat-") as tmp:
        playlist = Path(tmp) / "segments.ffconcat"
        # Paths are server-generated checkpoint names, never user-supplied media.
        lines = ["ffconcat version 1.0"]
        for path in paths:
            escaped = str(path.resolve()).replace("'", "'\\''")
            lines.append("file '" + escaped + "'")
            # Do not use concat's duration/outpoint directives: all MP4 chunks
            # are normalized by the same model and the final -t trims overshoot.
        playlist.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
             "-f", "concat", "-safe", "0", "-i", str(playlist),
             "-map", "0:v:0", "-map", "0:a?", "-t", str(params["duration"]),
             "-c", "copy", "-movflags", "+faststart", str(output)],
            capture_output=True, text=True, timeout=600,
        )
    if result.returncode != 0 or not output.is_file():
        raise RuntimeError("Long-Video konnte nicht verbunden werden: "
                           + result.stderr[-1500:])
    info = _probe_video(output)
    if abs(float(info["duration"]) - float(params["duration"])) > 0.6:
        raise RuntimeError("Long-Video-Länge weicht zu stark vom Ziel ab")
    return info


def generate_long_video(model, params, output, *, job_id, checkpoints,
                        resume_job, generate, cancel_event, response_callback,
                        progress_callback, phase_callback, update):
    if model.get("provider") != "ltx-mlx":
        raise ValueError("Long-Video ist nur für das native LTX-MLX-Modell verfügbar")
    plan = segment_plan(params["duration"], params["resolution"])
    directory = checkpoints / job_id
    directory.mkdir(parents=True, exist_ok=True)
    prior = (resume_job or {}).get("segments") or []
    previous_dir = checkpoints / resume_job["id"] if resume_job else None
    completed, paths = [], []

    for index, seconds in enumerate(plan):
        _check_cancel(cancel_event)
        update(scene_number=index + 1, scene_count=len(plan),
               segment_number=index + 1, segment_count=len(plan),
               segments=list(completed))
        clip = directory / f"segment-{index}.mp4"
        last_frame = directory / f"last-frame-{index}.png"
        reused = False
        if (index < len(prior) and previous_dir is not None
                and prior[index].get("index") == index
                and prior[index].get("seconds") == seconds):
            source = previous_dir / clip.name
            if source.is_file() and not source.is_symlink():
                try:
                    info = _probe_video(source)
                    if (info["width"], info["height"]) != (params["width"], params["height"]):
                        raise ValueError("Auflösung des Checkpoints geändert")
                    shutil.copy2(source, clip)
                    reused = True
                except (OSError, RuntimeError, ValueError, KeyError):
                    clip.unlink(missing_ok=True)

        if not reused:
            previous_frame = directory / f"last-frame-{index - 1}.png"
            if index and not previous_frame.is_file():
                _last_frame(paths[-1], previous_frame)
            segment = dict(params, duration=seconds,
                           frames=seconds * int(params["fps"]) + 1,
                           seed=(int(params["seed"]) + index) % (2 ** 31),
                           images=[], multi_image_mode=None, resume_from=None,
                           long_video=False,
                           first_frame=(str(previous_frame) if index else
                                        params.get("first_frame")))
            if index:
                segment["resize_mode"] = "contain"
            def on_progress(event):
                progress = float(event.get("progress") or 0)
                if progress > 1:
                    progress /= 100
                progress_callback(dict(event,
                    progress=0.9 * (index + min(1.0, max(0.0, progress))) / len(plan)))
            try:
                # A full-system snapshot includes Metal unified-memory pressure;
                # checking the worker's RSS alone would miss GPU allocations.
                runtime_coordinator.ensure_active_memory_safe(
                    runtime_coordinator.memory_budget_snapshot()
                )
                generate(model, segment, clip, cancel_event=cancel_event,
                         response_callback=response_callback,
                         progress_callback=on_progress,
                         phase_callback=phase_callback)
            except BaseException:
                clip.unlink(missing_ok=True)
                raise
            finally:
                # The normal short-video flow intentionally keeps a warm worker;
                # long clips must force a cold MLX/Metal release every segment.
                shutdown_warm_runtime()

        _check_cancel(cancel_event)
        info = _probe_video(clip)
        if (info["width"], info["height"]) != (params["width"], params["height"]):
            raise RuntimeError("Segmentauflösung weicht vom angeforderten Format ab")
        # The derived image is the input to the next segment. Extract before
        # marking this segment complete so a retry never inherits a broken clip.
        if index < len(plan) - 1:
            _last_frame(clip, last_frame)
        completed.append({"index": index, "seconds": seconds,
                          "reused": reused, **info})
        paths.append(clip)
        update(segments=list(completed))
        progress_callback({"progress": 0.9 * (index + 1) / len(plan)})

    _check_cancel(cancel_event)
    phase_callback("muxing")
    progress_callback({"phase": "muxing", "progress": 0.95})
    info = _concat_segments(paths, output, params)
    _check_cancel(cancel_event)
    shutil.rmtree(directory)
    return info | {"long_video": True, "segment_count": len(plan),
                   "segments": completed, "backend": "mlx"}
