"""Reproducible CPU-only media evidence and a human quality review protocol."""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import sys
import wave
from array import array
from pathlib import Path

from .telemetry import write_json

CATEGORIES = ("motion", "sharpness", "temporal_consistency", "faces_anatomy", "audio", "artifacts")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def pcm_metrics(path):
    with wave.open(str(path), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise ValueError("PCM evidence must be signed 16-bit")
        samples = array("h", wav.readframes(wav.getnframes()))
        if sys.byteorder != "little":
            samples.byteswap()
        count = len(samples)
        return {"sample_rate": wav.getframerate(), "channels": wav.getnchannels(),
                "duration_seconds": wav.getnframes() / wav.getframerate(),
                "peak_amplitude": max((abs(v) for v in samples), default=0) / 32768,
                "rms_amplitude": math.sqrt(sum(v * v for v in samples) / max(1, count)) / 32768,
                "clipped_sample_fraction": sum(abs(v) >= 32767 for v in samples) / max(1, count),
                "limitation": "Decoded codec output statistics, not a perceptual audio-quality score"}


def media_evidence(video, output_dir):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg and ffprobe required for video/audio validation")
    video, output_dir = Path(video), Path(output_dir)
    probe = json.loads(subprocess.check_output(
        [ffprobe, "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(video)],
        text=True, timeout=120))
    write_json(output_dir / "ffprobe.json", probe)
    streams = probe.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if len(videos) != 1 or not audios:
        raise RuntimeError("Generated artifact must contain video and audio")
    audio = output_dir / "audio.wav"
    subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-n", "-i", str(video), "-map", "0:a:0",
                    "-c:a", "pcm_s16le", str(audio)], check=True, timeout=120)
    hashes = output_dir / "video.framemd5"
    subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-n", "-i", str(video), "-map", "0:v:0",
                    "-f", "framemd5", str(hashes)], check=True, timeout=120)
    frame_count = int(videos[0].get("nb_read_frames") or 0)
    for index in sorted({0, frame_count // 2, max(0, frame_count - 1)}):
        subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-n", "-i", str(video),
                        "-vf", f"select=eq(n\\,{index})", "-frames:v", "1",
                        str(output_dir / f"frame-{index:04d}.png")], check=True, timeout=120)
    review = {"status": "pending_human_review", "scores": {key: None for key in CATEGORIES},
              "scale": "1 unacceptable .. 5 excellent; compare blind A/B at native resolution and normal speed",
              "instructions": ["View full clip and first/middle/last frames at native size",
                               "Inspect motion, edge/detail retention, flicker and scene continuity",
                               "Inspect face identity, lips, teeth, hands and anatomy where present",
                               "Listen on headphones: speech, noise, clipping, sync and ending",
                               "Reject any visible/audible regression; scores do not prove equivalence"],
              "regression": None, "reviewer": None, "notes": ""}
    write_json(output_dir / "quality-review.json", review)
    return {"video": str(video), "video_sha256": sha256(video), "audio": str(audio),
            "audio_sha256": sha256(audio), "frame_hashes": str(hashes),
            "review": str(output_dir / "quality-review.json"), "probe": probe,
            "audio_metrics": pcm_metrics(audio)}


def compare(reference, candidate, output):
    """No automatic quality pass: PSNR/SSIM compare decoded pixels, not latent parity."""
    reference, candidate = Path(reference).resolve(), Path(candidate).resolve()
    a, b = json.loads(reference.read_text()), json.loads(candidate.read_text())
    if a.get("status") != "completed" or b.get("status") != "completed":
        raise ValueError("Both runs must have completed")
    if a["input_fingerprint"] != b["input_fingerprint"]:
        raise ValueError("Seeds/prompts/media/geometry/schedules do not match")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg missing")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    metrics = {}
    for metric in ("psnr", "ssim"):
        p = subprocess.run([ffmpeg, "-nostdin", "-v", "info", "-i", a["artifacts"]["video"],
                            "-i", b["artifacts"]["video"], "-filter_complex",
                            f"[0:v]setpts=PTS-STARTPTS[a];[1:v]setpts=PTS-STARTPTS[b];[a][b]{metric}",
                            "-an", "-f", "null", "-"], text=True, capture_output=True, timeout=300, check=True)
        metrics[metric] = [line for line in p.stderr.splitlines() if metric.lower() in line.lower()]
    result = {"reference": str(reference), "candidate": str(candidate), "metrics": metrics,
              "decoded_frame_hashes_equal": Path(a["artifacts"]["frame_hashes"]).read_bytes()
                  == Path(b["artifacts"]["frame_hashes"]).read_bytes(),
              "audio_pcm_artifact_hash_equal": a["artifacts"]["audio_sha256"] == b["artifacts"]["audio_sha256"],
              "quality_accepted": None, "review_required": list(CATEGORIES),
              "limitation": "Codec output comparison; not a latent parity test. Human AV review required."}
    write_json(output / "comparison.json", result)
    return result
