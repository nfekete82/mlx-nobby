"""Bounded long-form LTX Talking Photo assembly, preserving the source speech WAV.

An audio-conditioned LTX job may handle at most 20 seconds. Longer utterances
are rendered sequentially, cut near quiet speech boundaries, and reassembled
with the unmodified full source audio as the *only* output audio track.
"""
from __future__ import annotations

from dataclasses import dataclass
from array import array
import hashlib
import io
import math
from pathlib import Path
import shutil
import subprocess
import time
import wave

from agent.talking_photo_audio import _read_pcm16_mono, validate_wav


MAX_LONGFORM_SECONDS = 60.0
CHUNK_TARGET_SECONDS = 14.0
CHUNK_MAX_SECONDS = 18.0
CHUNK_MIN_SECONDS = 4.0
FPS = 24
SAMPLE_RATE = 16000


@dataclass(frozen=True)
class AudioSegment:
    index: int
    start_frame: int
    end_frame: int
    start_sample: int
    end_sample: int
    wav: bytes

    @property
    def duration_seconds(self) -> float:
        return (self.end_sample - self.start_sample) / SAMPLE_RATE

    @property
    def video_frames(self) -> int:
        return self.end_frame - self.start_frame


def _write_wav(pcm: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm)
    return output.getvalue()


def split_at_pauses(source: bytes) -> list[AudioSegment]:
    """Split PCM once, on shared 24-fps boundaries; never drop or duplicate samples.

    Prefer low-energy ~180ms windows near 14s. With continuous speech the
    least energetic boundary is used; an exact word-boundary guarantee is not
    possible without speech transcription. Every part is <=18 seconds.
    """
    stats = validate_wav(source)
    duration = stats["frames"] / SAMPLE_RATE
    if duration > MAX_LONGFORM_SECONDS:
        raise RuntimeError(
            f"Talking Photo 2.0 unterstützt maximal {MAX_LONGFORM_SECONDS:g} Sekunden Audio."
        )
    rate, samples = _read_pcm16_mono(source)
    if rate != SAMPLE_RATE:
        raise RuntimeError("Longform benötigt 16 kHz Mono-PCM")
    total_samples = len(samples)
    total_frames = math.ceil(total_samples * FPS / SAMPLE_RATE)
    min_frames = int(CHUNK_MIN_SECONDS * FPS)
    max_frames = int(CHUNK_MAX_SECONDS * FPS)
    target_frames = int(CHUNK_TARGET_SECONDS * FPS)
    segments: list[AudioSegment] = []
    first_frame = 0
    first_sample = 0

    while total_frames - first_frame > max_frames:
        low = first_frame + min_frames
        # Reserve a minimum-length tail and stay <= 18s on each render.
        high = min(first_frame + max_frames, total_frames - min_frames)
        target = min(max(first_frame + target_frames, low), high)
        quiet = []
        fallback = []
        for boundary in range(low, high + 1):
            center = round(boundary * SAMPLE_RATE / FPS)
            radius = int(SAMPLE_RATE * 0.09)
            window = samples[max(0, center - radius):min(total_samples, center + radius)]
            peak = max((abs(value) for value in window), default=0)
            distance = abs(boundary - target)
            if peak < 300:  # ~-41dBFS peak; require a meaningful quiet interval
                quiet.append((distance, peak, boundary))
            fallback.append((peak, distance, boundary))
        if not fallback:
            raise RuntimeError("Kein gültiger Audio-Schnittpunkt")
        boundary = min(quiet)[2] if quiet else min(fallback)[2]
        last_sample = round(boundary * SAMPLE_RATE / FPS)
        pcm = samples[first_sample:last_sample]
        if not pcm:
            raise RuntimeError("Leerer Talking-Photo-Abschnitt")
        segment = AudioSegment(
            len(segments) + 1, first_frame, boundary, first_sample, last_sample,
            _write_wav(pcm.tobytes()),
        )
        validate_wav(segment.wav)
        segments.append(segment)
        first_frame, first_sample = boundary, last_sample

    tail = samples[first_sample:total_samples]
    final = AudioSegment(
        len(segments) + 1, first_frame, total_frames,
        first_sample, total_samples, _write_wav(tail.tobytes()),
    )
    validate_wav(final.wav)
    segments.append(final)
    if len(segments) > 6 or any(s.duration_seconds > CHUNK_MAX_SECONDS + 1 / SAMPLE_RATE for s in segments):
        raise RuntimeError("Talking-Photo-Abschnitte überschreiten das sichere Render-Limit")
    if sum(s.end_sample - s.start_sample for s in segments) != total_samples:
        raise RuntimeError("Audio-Schnitt hat Samples verloren")
    return segments


def assemble(
    source_wav: bytes,
    segments: list[AudioSegment],
    rendered_files: list[Path],
    work: Path,
    *,
    cancelled,
) -> tuple[bytes, dict]:
    """Join video-only trims on exact frame boundaries, then mux original WAV.

    The final audio is never constructed from per-clip conditioned/padded audio,
    so LTX's 8n+1 padding cannot introduce gaps between spoken phrases.
    """
    if cancelled():
        from agent.talking_photo_ltx import QualityCancelled
        raise QualityCancelled()
    if not segments or len(segments) != len(rendered_files):
        raise ValueError("Ungültige Longform-Abschnittsliste")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg wurde nicht gefunden")
    work.mkdir(parents=True, exist_ok=True)
    original_audio = work / "longform-source.wav"
    original_audio.write_bytes(source_wav)
    output = work / "longform-final.mp4"
    output.unlink(missing_ok=True)

    filters = []
    video_names = []
    for i, item in enumerate(segments):
        if not rendered_files[i].is_file():
            raise RuntimeError(f"Videoabschnitt {i + 1} fehlt")
        label = f"clip{i}"
        # Trimming frame-count instead of rounded seconds avoids padding at joins.
        filters.append(
            f"[{i}:v:0]fps={FPS},trim=end_frame={item.video_frames},"
            f"setpts=PTS-STARTPTS[{label}]"
        )
        video_names.append(f"[{label}]")
    filters.append(
        "".join(video_names) +
        f"concat=n={len(video_names)}:v=1:a=0[video]"
    )
    audio_index = len(rendered_files)
    duration = validate_wav(source_wav)["frames"] / SAMPLE_RATE
    command = [ffmpeg, "-y", "-v", "error"]
    for part in rendered_files:
        command.extend(["-i", str(part)])
    command.extend([
        "-i", str(original_audio),
        "-filter_complex", ";".join(filters),
        "-map", "[video]", "-map", f"{audio_index}:a:0",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{duration:.6f}", "-movflags", "+faststart",
        str(output),
    ])
    started = time.monotonic()
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        while True:
            if cancelled():
                from agent.talking_photo_ltx import QualityCancelled
                raise QualityCancelled()
            try:
                message, _ = process.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() - started > 180:
                    raise RuntimeError("Longform-Video-Zusammenführung hat das Zeitlimit überschritten")
        if process.returncode != 0:
            raise RuntimeError("Longform-Zusammenführung fehlgeschlagen: " + (message or "")[-1600:])
        video = output.read_bytes()
        if len(video) < 32 or b"ftyp" not in video[:32]:
            raise RuntimeError("Longform-Zusammenführung lieferte kein gültiges MP4")
        return video, {
            "source_audio_sha256": hashlib.sha256(source_wav).hexdigest(),
            "audio_seconds": round(duration, 4),
            "frames": sum(item.video_frames for item in segments),
            "fps": FPS,
            "segments": len(segments),
            "assembly_elapsed_seconds": round(time.monotonic() - started, 3),
            "assembly": "video-trim-concat / single original WAV mux",
        }
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if cancelled() or process.returncode != 0:
            output.unlink(missing_ok=True)
