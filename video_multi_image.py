"""Multi-image orchestration inside the existing native video job/lease.

No model is loaded here. Scene checkpoints belong to the durable video job;
only failed/cancelled jobs retain them for an explicit retry.
"""
from __future__ import annotations

import ast
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from video_providers import FFMPEG, ProviderCancelled, _probe_video


def keyframe_capabilities(runtime_root):
    """Inspect the installed editable runtime without importing MLX/allocating Metal."""
    package = Path(runtime_root) / "packages/ltx-pipelines-mlx/src/ltx_pipelines_mlx"
    try:
        def accepts(filename, name, argument):
            tree = ast.parse((package / filename).read_text())
            return any(
                isinstance(node, ast.FunctionDef) and node.name == name
                and argument in {a.arg for a in node.args.args + node.args.kwonlyargs}
                for node in ast.walk(tree)
            )
        args_source = (package / "utils/args.py").read_text()
        # Upstream v0.18 moves the dataclass to utils/types.py while keeping
        # the public import from utils.args. Probe both versions without MLX.
        try:
            types_source = (package / "utils/types.py").read_text()
        except OSError:
            types_source = ""
        image_contract = (
            "class ImageConditioningInput" in args_source
            or (
                "ImageConditioningInput" in args_source
                and "class ImageConditioningInput" in types_source
                and "def at(" in types_source
            )
        )
        supported = (
            accepts("distilled.py", "generate_two_stage", "images")
            and accepts("ti2vid_two_stages.py", "generate_and_save", "images")
            and image_contract
        )
    except (OSError, SyntaxError, ValueError):
        supported = False
    return {"native_keyframes": supported, "scenes": True, "min_images": 2,
            "max_images": 5, "frame_positions": "pixel_frames" if supported else None,
            "conditioning_strength": [0.0, 1.0] if supported else None}


def frame_positions(count, frames):
    """Include the first and final pixel frames, with evenly spaced interior anchors."""
    return [round(index * (frames - 1) / (count - 1)) for index in range(count)]


def run_ffmpeg(command, cancel_event, timeout=600):
    # A file keeps stderr bounded in RAM and avoids filling an unread pipe.
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if cancel_event.wait(0.2):
                    raise ProviderCancelled("Video job was cancelled")
                if time.monotonic() >= deadline:
                    raise RuntimeError("Zeitlimit beim Verbinden der Videos erreicht")
            if process.returncode:
                log.seek(0, 2)
                log.seek(max(0, log.tell() - 2000))
                raise RuntimeError("Videos konnten nicht verbunden werden: " + log.read().decode(errors="replace"))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def compose_scenes(paths, output, params, cancel_event):
    """Normalize all streams and concatenate; fill missing audio with silence."""
    command = [FFMPEG, "-hide_banner", "-nostdin", "-y"]
    filters, streams = [], []
    for index, path in enumerate(paths):
        info = _probe_video(path)
        command += ["-i", str(path)]
        width, height, fps = params["width"], params["height"], params["fps"]
        duration = min(float(info["duration"]), float(params["duration"]))
        if duration <= 0:
            raise RuntimeError("Videosegment ist leer")
        filters.append(
            f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},"
            f"trim=duration={duration},setpts=PTS-STARTPTS,format=yuv420p[v{index}]"
        )
        audio = (f"[{index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad"
                 if info["audio"] else "anullsrc=r=48000:cl=stereo")
        filters.append(f"{audio},atrim=duration={duration},asetpts=PTS-STARTPTS[a{index}]")
        streams.append(f"[v{index}][a{index}]")
    filters.append("".join(streams) + f"concat=n={len(paths)}:v=1:a=1[v][a]")
    command += ["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "48000", "-movflags", "+faststart", str(output)]
    run_ffmpeg(command, cancel_event)
    return _probe_video(output)


def generate_scenes(model, params, output, *, job_id, checkpoints, resume_job,
                    generate, cancel_event, response_callback, progress_callback,
                    phase_callback, update):
    directory = checkpoints / job_id
    directory.mkdir(parents=True, exist_ok=True)
    images = params["images"]
    completed, paths = [], []
    previous = (resume_job or {}).get("segments") or []
    for index, image in enumerate(images):
        if cancel_event.is_set():
            raise ProviderCancelled("Video job was cancelled")
        update(scene_number=index + 1, scene_count=len(images), segments=list(completed))
        path = directory / f"scene-{index}.mp4"
        reused = False
        if index < len(previous):
            source = checkpoints / resume_job["id"] / f"scene-{index}.mp4"
            if source.is_file() and not source.is_symlink():
                try:
                    _probe_video(source)
                    shutil.copy2(source, path)
                    reused = True
                except (OSError, RuntimeError, ValueError):
                    pass
        def progress(event):
            value = event.get("progress", 0)
            value = float(value or 0)
            if value > 1:
                value /= 100
            progress_callback(dict(event, progress=0.9 * (index + min(1, max(0, value))) / len(images)))
        if not reused:
            segment = dict(params, images=[], multi_image_mode=None, resume_from=None,
                           first_frame=image["path"], seed=(params["seed"] + index) % (2**31))
            try:
                generate(model, segment, path, cancel_event=cancel_event,
                         response_callback=response_callback, progress_callback=progress,
                         phase_callback=phase_callback)
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        info = _probe_video(path)
        completed.append({"index": index, "reused": reused, **info})
        paths.append(path)
        update(segments=list(completed))
        progress_callback({"progress": 0.9 * (index + 1) / len(images)})
    phase_callback("muxing")
    progress_callback({"phase": "muxing", "progress": 0.95})
    media = compose_scenes(paths, output, params, cancel_event)
    if cancel_event.is_set():
        raise ProviderCancelled("Video job was cancelled")
    # Checkpoints are durable on failure; successful jobs need only their final MP4.
    shutil.rmtree(directory)
    return media | {"scene_count": len(images), "segments": completed, "backend": "mlx"}
