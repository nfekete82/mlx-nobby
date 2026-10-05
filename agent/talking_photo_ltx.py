"""LTX-2.5 MLX Audio-to-Video renderer for high-quality Talking Photo beta."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time

import runtime_coordinator


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
    if seconds <= 0:
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
) -> tuple[bytes, dict]:
    """Generate a short audio-conditioned talking portrait without MuseTalk."""
    health = provider_health()
    if not health["ready"]:
        raise RuntimeError(health["detail"] or "LTX Quality ist nicht bereit")

    frames, clip_seconds = quality_frames(audio_seconds)
    source_image = work / f"ltx-quality-source{image_suffix}"
    source_audio = work / "ltx-quality-source.wav"
    padded_audio = work / "ltx-quality-audio.wav"
    output = work / "ltx-quality.mp4"
    source_image.write_bytes(image)
    source_audio.write_bytes(audio_wav)
    width, height = _image_size(source_image)
    target_width, target_height = target_dimensions(width, height)
    _pad_audio(source_audio, padded_audio, clip_seconds)
    seed = int.from_bytes(job_id.encode("utf-8")[:4].ljust(4, b"0"), "big") & 0x7FFFFFFF

    command = [
        str(RUNTIME_PYTHON), str(RUNNER),
        "--model", str(MODEL_DIR),
        "--image", str(source_image),
        "--audio", str(padded_audio),
        "--output", str(output),
        "--prompt", TALKING_PROMPT,
        "--width", str(target_width),
        "--height", str(target_height),
        "--frames", str(frames),
        "--fps", str(FPS),
        "--seed", str(seed),
        "--stage1-steps", "15",
        "--stage2-steps", "3",
    ]
    cancel_proxy = _CancelProxy(cancelled)
    started = time.monotonic()
    if update is not None:
        update(phase="quality", progress=0.25)

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
    return video, {
        "provider": "ltx-2.5-mlx-a2v",
        "frames": frames,
        "fps": FPS,
        "duration": clip_seconds,
        "width": target_width,
        "height": target_height,
        "stage_1_steps": 15,
        "stage_2_steps": 3,
        "low_ram": True,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
