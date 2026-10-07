"""LTX-2.5 MLX Audio-to-Video renderer for high-quality Talking Photo beta."""

from __future__ import annotations

import json
import hashlib
import math
import os
from pathlib import Path
import shutil
import subprocess
import time

import runtime_coordinator
from agent.talking_photo_audio import validate_wav


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path(os.environ.get(
    "LTX_MLX_RUNTIME_ROOT",
    str(Path.home() / ".local/share/mlx-nobby/ltx-2-mlx"),
)).expanduser()
RUNTIME_PYTHON = Path(os.environ.get(
    "LTX_MLX_PYTHON",
    str(RUNTIME_ROOT / ".venv/bin/python"),
)).expanduser()
MODEL_ROOT = Path(os.environ.get(
    "LTX_MLX_MODEL_ROOT",
    str(Path.home() / ".local/share/mlx-nobby/models"),
)).expanduser()
MODEL_DIR = MODEL_ROOT / "ltx-2.5-mlx-q4"
RUNNER = PROJECT_ROOT / "scripts/ltx-talking-photo-a2v.py"
MLX_MANAGER = PROJECT_ROOT / "scripts/mlx"
MLX_SERVER_LABEL = "de.nobby.mlx-server"
MAX_AUDIO_SECONDS = 10.0
FPS = 24
NEGATIVE_PROMPT = (
    "deformed mouth, warped lips, extra teeth, duplicated teeth, unstable teeth, "
    "distorted face, identity drift, exaggerated mouth opening, rubbery face, "
    "flicker, jitter, camera movement, zoom, scene change, extra people"
)

TALKING_PROMPT = (
    "The exact same person from the reference image speaks directly to camera in precise synchronization "
    "with the provided speech audio. Preserve the person's identity, facial features, skin texture, hairstyle, "
    "clothing, background, lighting and framing. Use natural realistic lip articulation matching the phonemes, "
    "stable teeth and mouth interior, subtle jaw and cheek motion, occasional natural blinking, tiny head motion "
    "and gentle breathing. Keep the face stable and mostly facing the camera. No exaggerated mouth opening, no "
    "identity drift, no camera movement, no zoom and no scene change."
)


class QualityCancelled(RuntimeError):
    pass


def resolve_seed(job_id: str) -> int:
    value = os.environ.get("LTX_TALKING_PHOTO_SEED")
    if value is None:
        return int.from_bytes(job_id.encode("utf-8")[:4].ljust(4, b"0"), "big") & 0x7FFFFFFF
    try:
        seed = int(value)
    except ValueError as exc:
        raise RuntimeError("LTX_TALKING_PHOTO_SEED muss eine Ganzzahl sein") from exc
    if not 0 <= seed <= 0x7FFFFFFF:
        raise RuntimeError("LTX_TALKING_PHOTO_SEED muss zwischen 0 und 2147483647 liegen")
    return seed


def debug_directory(job_id: str) -> Path | None:
    root = os.environ.get("LTX_TALKING_PHOTO_DEBUG_ROOT")
    if root:
        return Path(root).expanduser() / job_id
    if os.environ.get("LTX_TALKING_PHOTO_DEBUG", "").lower() in {"1", "true", "yes"}:
        return Path.home() / ".config/mlx-web/talking-photo/render-debug" / job_id
    return None


class _CancelProxy:
    def __init__(self, callback):
        self.callback = callback

    def is_set(self):
        return bool(self.callback())


def provider_health() -> dict:
    missing = []
    if not RUNTIME_PYTHON.is_file() or not os.access(RUNTIME_PYTHON, os.X_OK):
        missing.append(str(RUNTIME_PYTHON))
    if not RUNNER.is_file():
        missing.append(str(RUNNER))
    if not MODEL_DIR.is_dir() or not (MODEL_DIR / "embedded_config.json").is_file():
        missing.append(str(MODEL_DIR))
    ready = not missing
    return {
        "ready": ready,
        "provider": "ltx-2.5-mlx-a2v",
        "device": "mlx/metal" if ready else None,
        "max_audio_seconds": MAX_AUDIO_SECONDS,
        "setup_command": "./scripts/setup-ltx-video-mlx",
        "detail": None if ready else "LTX Quality fehlt: " + ", ".join(missing),
    }


def quality_frames(audio_seconds: float, fps: int = FPS) -> tuple[int, float]:
    """Cover all speech with the next valid LTX frame count, adding tiny silence if needed."""
    seconds = float(audio_seconds)
    if not math.isfinite(seconds) or seconds <= 0 or fps <= 0:
        raise RuntimeError("Talking-Photo-Audio ist leer")
    if seconds > MAX_AUDIO_SECONDS:
        raise RuntimeError(
            f"LTX Quality Beta unterstützt derzeit maximal {MAX_AUDIO_SECONDS:g} Sekunden Audio. "
            "Bitte einen kürzeren Testtext verwenden."
        )
    required = max(9, int(math.ceil(seconds * fps)))
    frames = 1 + 8 * int(math.ceil((required - 1) / 8))
    return frames, frames / fps


def target_dimensions(width: int, height: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise RuntimeError("Talking-Photo-Bildgröße ist ungültig")
    ratio = width / height
    if ratio < 0.9:
        return 512, 704
    if ratio > 1.1:
        return 704, 512
    return 640, 640


def _image_size(path: Path) -> tuple[int, int]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe wurde nicht gefunden")
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError("Bildgröße konnte nicht gelesen werden")
    streams = json.loads(result.stdout).get("streams") or []
    if not streams:
        raise RuntimeError("Bild enthält keinen lesbaren Frame")
    return int(streams[0]["width"]), int(streams[0]["height"])


def _pad_audio(source: Path, target: Path, duration: float) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg wurde nicht gefunden")
    result = subprocess.run(
        [
            ffmpeg, "-y", "-v", "error", "-i", str(source),
            "-af", "apad", "-t", f"{duration:.6f}",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target),
        ],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0 or not target.is_file():
        raise RuntimeError("A2V-Audio konnte nicht vorbereitet werden: " + (result.stderr or "")[-1000:])


def _chat_loaded() -> bool:
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{MLX_SERVER_LABEL}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _chat_command(action: str) -> None:
    result = subprocess.run(
        ["/bin/bash", str(MLX_MANAGER), action],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stdout.strip() or f"mlx {action} fehlgeschlagen")[-4000:])


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def generate(
    job_id: str,
    image: bytes,
    image_suffix: str,
    audio_wav: bytes,
    audio_seconds: float,
    work: Path,
    *,
    cancelled,
    update=None,
    debug_dir: Path | None = None,
) -> tuple[bytes, dict]:
    """Generate a short audio-conditioned talking portrait without MuseTalk."""
    health = provider_health()
    if not health["ready"]:
        raise RuntimeError(health["detail"] or "LTX Quality ist nicht bereit")

    seed = resolve_seed(job_id)
    source_stats = validate_wav(audio_wav)
    # The WAV header is authoritative, rather than a caller's duration estimate.
    audio_seconds = source_stats["frames"] / source_stats["sample_rate"]
    frames, clip_seconds = quality_frames(audio_seconds)
    debug_dir = debug_dir if debug_dir is not None else debug_directory(job_id)
    work = work.resolve()
    if debug_dir is not None:
        debug_dir = debug_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
    source_image = work / f"ltx-quality-source{image_suffix}"
    source_audio = work / "ltx-quality-source.wav"
    padded_audio = work / "ltx-quality-audio.wav"
    output = work / "ltx-quality.mp4"
    source_image.write_bytes(image)
    source_audio.write_bytes(audio_wav)
    width, height = _image_size(source_image)
    target_width, target_height = target_dimensions(width, height)
    _pad_audio(source_audio, padded_audio, clip_seconds)
    padded_stats = validate_wav(padded_audio.read_bytes())
    if abs(padded_stats["frames"] / 16000 - clip_seconds) > 1 / 16000:
        raise RuntimeError("LTX-Audio-Padding passt nicht zur Videodauer")
    if debug_dir is not None:
        shutil.copy2(source_image, debug_dir / source_image.name)
        shutil.copy2(source_audio, debug_dir / source_audio.name)
        # Use the retained file itself in --audio, so there is no ambiguity.
        shutil.copy2(padded_audio, debug_dir / padded_audio.name)
        source_image = (debug_dir / source_image.name).resolve()
        padded_audio = (debug_dir / padded_audio.name).resolve()
    runner_diagnostics = (debug_dir or work) / "runner.json"

    command = [
        str(RUNTIME_PYTHON), str(RUNNER),
        "--model", str(MODEL_DIR),
        "--image", str(source_image),
        "--audio", str(padded_audio),
        "--output", str(output),
        "--prompt", TALKING_PROMPT,
        "--negative-prompt", NEGATIVE_PROMPT,
        "--width", str(target_width),
        "--height", str(target_height),
        "--frames", str(frames),
        "--fps", str(FPS),
        "--seed", str(seed),
        "--stage1-steps", "15",
        "--stage2-steps", "3",
        "--cfg-scale", "3.0",
        "--stg-scale", "1.0",
        "--diagnostics", str(runner_diagnostics.resolve()),
    ]
    details = {
        "provider": "ltx-2.5-mlx-a2v", "seed": seed,
        "seed_source": "environment" if "LTX_TALKING_PHOTO_SEED" in os.environ else "job_id",
        "prompt": TALKING_PROMPT, "negative_prompt": NEGATIVE_PROMPT,
        "frames": frames, "fps": FPS, "duration": clip_seconds,
        "audio_seconds": audio_seconds, "source_audio_stats": source_stats,
        "conditioning_audio_stats": padded_stats,
        "conditioning_audio_sha256": hashlib.sha256(padded_audio.read_bytes()).hexdigest(),
        "image_sha256": hashlib.sha256(image).hexdigest(),
        "width": target_width, "height": target_height,
        "stage_1_steps": 15, "stage_2_steps": 3, "cfg_scale": 3.0, "stg_scale": 1.0,
        "low_ram": True, "low_memory": True, "command": command,
        "audio_path": str(padded_audio),
        "debug_dir": str(debug_dir.resolve()) if debug_dir is not None else None,
        "status": "prepared",
    }
    def save_details():
        if debug_dir is not None:
            (debug_dir / "render.json").write_text(
                json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
            )
    save_details()
    cancel_proxy = _CancelProxy(cancelled)
    started = time.monotonic()
    if update is not None:
        update(phase="quality", progress=0.25)

    details["status"] = "rendering"
    save_details()
    try:
        try:
            with runtime_coordinator.video_runtime(
                cancel_proxy,
                chat_loaded=_chat_loaded,
                chat_command=_chat_command,
            ):
                if cancelled():
                    raise QualityCancelled()
                process = subprocess.Popen(
                    command,
                    cwd=RUNTIME_ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                output_text = ""
                try:
                    while True:
                        if cancelled():
                            _terminate(process)
                            raise QualityCancelled()
                        try:
                            stdout, _ = process.communicate(timeout=0.5)
                            output_text = stdout or ""
                            if debug_dir is not None:
                                (debug_dir / "ltx.log").write_text(output_text, encoding="utf-8")
                            break
                        except subprocess.TimeoutExpired:
                            if update is not None:
                                elapsed = time.monotonic() - started
                                # Coarse truthful progress only; A2V currently has no stable machine progress API.
                                update(phase="quality", progress=min(0.88, 0.3 + elapsed / 900.0))
                            continue
                finally:
                    if cancelled() and process.poll() is None:
                        _terminate(process)
                if process.returncode != 0:
                    raise RuntimeError(
                        "LTX Quality fehlgeschlagen" + (f": {output_text[-3000:].strip()}" if output_text else "")
                    )
        except runtime_coordinator.CoordinationCancelled as exc:
            raise QualityCancelled() from exc

        if not output.is_file():
            raise RuntimeError("LTX Quality lieferte kein Video")
        video = output.read_bytes()
        if len(video) < 32 or b"ftyp" not in video[:32]:
            raise RuntimeError("LTX Quality lieferte kein gültiges MP4")
        details["status"] = "completed"
        details["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if runner_diagnostics.is_file():
            details["runner"] = json.loads(runner_diagnostics.read_text(encoding="utf-8"))
        if debug_dir is not None:
            shutil.copy2(output, debug_dir / "output.mp4")
            details["output_path"] = str((debug_dir / "output.mp4").resolve())
        save_details()
        return video, details
    except QualityCancelled:
        details.update(status="cancelled", elapsed_seconds=round(time.monotonic() - started, 3))
        save_details()
        raise
    except Exception as exc:
        details.update(status="failed", error=str(exc),
                       elapsed_seconds=round(time.monotonic() - started, 3))
        save_details()
        raise
