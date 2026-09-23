"""Headless LTX 2.5 provider using Lightricks' official local MPS backend."""
import concurrent.futures
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import video_registry


LTX_RUNTIME_ROOT = Path(os.environ.get(
    "LTX_RUNTIME_ROOT",
    str(Path.home() / ".local/share/mlx-nobby/LTX-Desktop"),
)).expanduser()
LTX_BACKEND = LTX_RUNTIME_ROOT / "backend"
LTX_PYTHON = Path(os.environ.get("LTX_PYTHON", str(LTX_BACKEND / ".venv/bin/python"))).expanduser()
LTX_SERVER = LTX_BACKEND / "ltx2_server.py"
LTX_URL = os.environ.get("LTX_URL", "http://127.0.0.1:18060").rstrip("/")
LTX_PORT = int(LTX_URL.rsplit(":", 1)[-1])
LTX_AUTH_TOKEN = os.environ.get("LTX_AUTH_TOKEN", "mlx-nobby-video-local")
FFMPEG = os.environ.get("FFMPEG_PATH", "/opt/homebrew/bin/ffmpeg")
FFPROBE = os.environ.get("FFPROBE_PATH", str(Path(FFMPEG).with_name("ffprobe")))
IMAGE_ROOT = Path.home() / ".config/mlx-web/images"
UPLOAD_ROOT = Path.home() / ".config/mlx-web/batch/uploads"
RUNTIME_LOG = Path.home() / ".config/mlx-web/ltx-runtime.log"
SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class ProviderCancelled(RuntimeError):
    pass


def _headers():
    return {
        "Authorization": f"Bearer {LTX_AUTH_TOKEN}",
        "Content-Type": "application/json",
    }


def _json_request(method, path, payload=None, timeout=30):
    request = urllib.request.Request(
        LTX_URL + path,
        method=method,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers=_headers(),
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def availability(model):
    if not video_registry.local_files_available(model):
        missing = video_registry.missing_files(model)
        return False, "Lokale LTX-2.5-Gewichte fehlen: " + ", ".join(missing)
    if not LTX_PYTHON.is_file() or not LTX_SERVER.is_file():
        return False, f"Offizielle LTX-Runtime fehlt unter {LTX_RUNTIME_ROOT}"
    return True, "LTX 2.5 Fast ist lokal über das offizielle MPS-Backend verfügbar"


def validate_first_frame(value):
    if value is None:
        return None
    source = Path(str(value)).expanduser().resolve()
    roots = {IMAGE_ROOT.resolve(), UPLOAD_ROOT.resolve()}
    if source.parent not in roots or source.suffix.lower() not in SUPPORTED_SUFFIXES or not source.is_file():
        raise ValueError("I2V benötigt ein verwaltetes lokales Bildartefakt oder Chat-Upload")
    return source


def i2v_source_size(source):
    command = [
        FFPROBE, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", str(source),
    ]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
    if completed.returncode != 0:
        raise ValueError("Bildgröße konnte nicht gelesen werden")
    streams = json.loads(completed.stdout).get("streams") or []
    if not streams:
        raise ValueError("Bild enthält keinen lesbaren Frame")
    width, height = int(streams[0]["width"]), int(streams[0]["height"])
    if width <= 0 or height <= 0:
        raise ValueError("Bildgröße ist ungültig")
    return width, height


def i2v_aspect_ratio(source_width, source_height):
    ratio = source_width / source_height
    return "9:16" if ratio < 0.9 else "16:9"


def i2v_target_size(source_width, source_height, quality=None):
    resolution = {"fast": "540p", "standard": "720p", "quality": "1080p"}.get(
        quality or "standard", "720p",
    )
    landscape = {
        "540p": (1024, 576), "720p": (1280, 704), "1080p": (1920, 1088),
    }[resolution]
    if 0.9 <= source_width / source_height <= 1.1:
        square = {"540p": 768, "720p": 1024, "1080p": 1088}[resolution]
        return square, square
    return landscape if source_width > source_height else tuple(reversed(landscape))


def _runtime_canvas(resolution, aspect_ratio):
    landscape = {
        "540p": (1024, 576), "720p": (1280, 704), "1080p": (1920, 1088),
    }[resolution]
    return tuple(reversed(landscape)) if aspect_ratio == "9:16" else landscape


def i2v_contained_size(source_width, source_height, target_width, target_height):
    scale = min(target_width / source_width, target_height / source_height)
    return source_width * scale, source_height * scale


def _prepare_first_frame(source, target_width, target_height, resize_mode, destination):
    if resize_mode not in {"contain", "cover"}:
        raise ValueError("I2V resize_mode muss 'contain' oder 'cover' sein")
    source_width, source_height = i2v_source_size(source)
    if resize_mode == "cover":
        video_filter = (
            f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase:"
            f"force_divisible_by=2,crop={target_width}:{target_height},setsar=1"
        )
    else:
        video_filter = (
            f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease:"
            f"force_divisible_by=2,pad={target_width}:{target_height}:"
            "(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
        )
    completed = subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", str(source), "-vf", video_filter,
         "-frames:v", "1", str(destination)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120,
    )
    if completed.returncode != 0 or not destination.is_file():
        raise RuntimeError("First Frame konnte nicht vorbereitet werden: " + completed.stderr[-1000:])
    return {
        "source_width": source_width, "source_height": source_height,
        "target_width": target_width, "target_height": target_height,
        "resize_mode": resize_mode,
    }


def _finalize_video(source, output, target_width, target_height, runtime_width, runtime_height):
    output.parent.mkdir(parents=True, exist_ok=True)
    if (target_width, target_height) == (runtime_width, runtime_height):
        shutil.copy2(source, output)
        return
    # LTX Desktop currently exposes only 16:9 and 9:16 generation canvases.
    # Preserve a square I2V result by containing that canvas in a square MP4;
    # this deliberately pads instead of stretching or implicitly cropping.
    video_filter = (
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease:"
        f"force_divisible_by=2,pad={target_width}:{target_height}:"
        "(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
    )
    completed = subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", str(source), "-map", "0:v:0",
         "-map", "0:a?", "-vf", video_filter, "-c:v", "libx264", "-crf", "18",
         "-preset", "medium", "-c:a", "copy", "-movflags", "+faststart", str(output)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1800,
    )
    if completed.returncode != 0 or not output.is_file():
        raise RuntimeError("Video konnte nicht geometriegetreu finalisiert werden: " + completed.stderr[-1000:])


def _runtime_environment():
    environment = os.environ.copy()
    environment.update({
        "LTX_APP_DATA_DIR": str(video_registry.LTX_APP_DATA),
        "LTX_PORT": str(LTX_PORT),
        "LTX_AUTH_TOKEN": LTX_AUTH_TOKEN,
        "LTX_ADMIN_TOKEN": LTX_AUTH_TOKEN,
        "PYTORCH_ENABLE_MPS_FALLBACK": "1",
        "PATH": str(LTX_PYTHON.parent) + os.pathsep + environment.get("PATH", ""),
    })
    return environment


def _start_runtime(cancel_event):
    RUNTIME_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = RUNTIME_LOG.open("ab", buffering=0)
    process = subprocess.Popen(
        [str(LTX_PYTHON), str(LTX_SERVER)], cwd=LTX_BACKEND,
        env=_runtime_environment(), stdout=log, stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + 180
    try:
        while time.monotonic() < deadline:
            if cancel_event.is_set():
                raise ProviderCancelled("Video job was cancelled")
            if process.poll() is not None:
                raise RuntimeError(f"LTX-Backend wurde unerwartet beendet (Exit {process.returncode})")
            try:
                _json_request("GET", "/health", timeout=3)
                policy = _json_request("GET", "/api/runtime-policy", timeout=3)
                if policy.get("force_api_generations"):
                    raise RuntimeError(
                        "LTX Memory-Preflight fehlgeschlagen: weniger als 15 GB RAM frei"
                    )
                _json_request("POST", "/api/settings", {
                    "useLocalTextEncoder": True,
                    "userPrefersLtxApiVideoGenerations": False,
                    "promptEnhancerEnabledT2V": False,
                    "promptEnhancerEnabledI2V": False,
                    "activeLtxModelId": video_registry.LTX_ID,
                    "useConvVae": True,
                }, timeout=10)
                return process, log
            except urllib.error.URLError:
                time.sleep(0.5)
        raise RuntimeError("LTX-Backend wurde nicht rechtzeitig bereit")
    except Exception:
        _stop_runtime(process, log)
        raise


def _stop_runtime(process, log):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    log.close()


def unload(runtime):
    if runtime:
        _stop_runtime(*runtime)


def _probe_video(path):
    completed = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries",
         "stream=index,codec_type,width,height,avg_frame_rate,nb_frames:format=duration",
         "-of", "json", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError("LTX-Ausgabe ist kein lesbares MP4: " + completed.stderr[-1000:])
    data = json.loads(completed.stdout)
    streams = data.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not video:
        raise RuntimeError("LTX-Ausgabe enthält keinen Videostream")
    numerator, denominator = (video.get("avg_frame_rate") or "24/1").split("/", 1)
    fps = float(numerator) / max(float(denominator), 1.0)
    duration = float((data.get("format") or {}).get("duration") or 0)
    frames = int(video.get("nb_frames") or round(duration * fps))
    return {
        "frames": frames, "width": int(video["width"]), "height": int(video["height"]),
        "fps": fps, "duration": duration,
        "audio": any(item.get("codec_type") == "audio" for item in streams),
    }


def _generate_request(payload):
    return _json_request("POST", "/api/generate", payload, timeout=7200)


def generate(model, params, output, *, cancel_event, response_callback=None,
             progress_callback=None, phase_callback=None):
    ready, reason = availability(model)
    if not ready:
        raise RuntimeError(reason)
    source = validate_first_frame(params.get("first_frame"))
    runtime = _start_runtime(cancel_event)
    if response_callback:
        response_callback(runtime)
    resize_info = {}
    try:
        width, height = int(params["width"]), int(params["height"])
        runtime_width, runtime_height = _runtime_canvas(
            params["resolution"], params["aspect_ratio"],
        )
        payload = {
            "prompt": params["prompt"], "resolution": params["resolution"],
            "model": "fast", "duration": params["duration"], "fps": params["fps"],
            "aspectRatio": params["aspect_ratio"], "seed": params["seed"], "audio": True,
        }
        with tempfile.TemporaryDirectory(prefix="mlx-ltx-i2v-") as temporary:
            if source:
                prepared = Path(temporary) / "first-frame.png"
                resize_info = _prepare_first_frame(
                    source, runtime_width, runtime_height,
                    params.get("resize_mode") or "contain", prepared,
                )
                resize_info.update({
                    "target_width": width, "target_height": height,
                    "conditioning_width": runtime_width,
                    "conditioning_height": runtime_height,
                })
                payload["imagePath"] = str(prepared)
            if phase_callback:
                phase_callback("encoding")
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_generate_request, payload)
                cancel_sent = False
                while not future.done():
                    if cancel_event.is_set() and not cancel_sent:
                        cancel_sent = True
                        try:
                            _json_request("POST", "/api/generate/cancel", {}, timeout=10)
                        except Exception:
                            pass
                    if cancel_sent and future.done():
                        break
                    try:
                        progress = _json_request("GET", "/api/generation/progress", timeout=5)
                        phase = str(progress.get("phase") or "")
                        if phase_callback and phase:
                            phase_callback(phase)
                        if progress_callback:
                            progress_callback({
                                "phase": phase,
                                "step": progress.get("currentStep"),
                                "total_steps": progress.get("totalSteps"),
                                "progress": progress.get("progress"),
                            })
                    except Exception:
                        pass
                    time.sleep(0.5)
                result = future.result()
            if cancel_event.is_set() or result.get("status") == "cancelled":
                raise ProviderCancelled("Video job was cancelled")
            source_output = Path(str(result.get("video_path") or ""))
            if result.get("status") != "complete" or not source_output.is_file():
                raise RuntimeError("LTX-Backend lieferte kein Video")
            if phase_callback:
                phase_callback("muxing")
            if progress_callback:
                progress_callback({"phase": "muxing", "progress": 98})
            _finalize_video(
                source_output, output, width, height, runtime_width, runtime_height,
            )
        return _probe_video(output) | resize_info | {"provider_payload": payload}
    finally:
        if response_callback:
            response_callback(None)
        unload(runtime)
