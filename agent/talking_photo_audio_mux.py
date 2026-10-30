"""Publish the exact Qwen3-TTS speech track rather than generated LTX audio.

Only used by the opt-in chat voice-video workflow. Never synthesizes or
translates speech. Video frames stay unchanged (stream copy).
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


def preserve_speech(video: bytes, tts_wav: bytes, work: Path) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg fehlt: Originalsprache kann nicht zuverlässig übernommen werden")
    work.mkdir(parents=True, exist_ok=True)
    source_video = work / "ltx-video-for-audio-mux.mp4"
    source_audio = work / "requested-tts-speech.wav"
    output = work / "ltx-video-with-original-speech.mp4"
    source_video.write_bytes(video)
    source_audio.write_bytes(tts_wav)
    try:
        completed = subprocess.run([
            ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-i", str(source_video),
            "-i", str(source_audio),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-af", "apad", "-shortest",
            "-movflags", "+faststart", str(output),
        ], capture_output=True, text=True, timeout=120, check=False)
        if completed.returncode != 0 or not output.is_file() or output.stat().st_size < 32:
            raise RuntimeError("Original-TTS-Audio konnte nicht in das Video übernommen werden: " +
                               completed.stderr[-400:])
        return output.read_bytes()
    finally:
        source_video.unlink(missing_ok=True)
        source_audio.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
