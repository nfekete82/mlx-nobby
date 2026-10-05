#!/usr/bin/env python3
"""Calibrate Talking Photo clone voices against the real default TTS voice.

The tool intentionally does not auto-apply profiles. It renders the same sentence
with every clone voice at several native TTS speeds, measures the exact 16 kHz WAV,
and writes a report plus listenable WAV candidates below:

    ~/.config/mlx-web/talking-photo/calibration/<timestamp>/

Run from the repository root while the speech service is running:

    python3 scripts/calibrate-talking-photo-voices.py
"""

from __future__ import annotations

import argparse
from array import array
from datetime import datetime
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import wave


DEFAULT_SPEECH_URL = os.environ.get(
    "SPEECH_SERVICE_URL", "http://127.0.0.1:8050"
).rstrip("/")
DEFAULT_TEXT = "Hallo, das ist ein kurzer Test meiner Stimme."
DEFAULT_SPEEDS = (1.0, 0.9, 0.8, 0.7)
SILENCE_DBFS = -45.0
WINDOW_MS = 10.0


def _http_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f"Speech-Service nicht erreichbar: {exc}") from exc


def _tts(base_url: str, text: str, language: str, voice: str | None, speed: float) -> bytes:
    payload: dict[str, object] = {
        "input": text,
        "language": language,
    }
    if voice:
        payload["voice"] = voice
    if speed != 1.0:
        payload["speed"] = speed
    request = urllib.request.Request(
        base_url + "/v1/audio/speech",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "audio/mpeg, audio/wav, application/octet-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            audio = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Speech-Service {exc.code}: {detail[:1000]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Speech-Service nicht erreichbar: {exc}") from exc
    if not audio:
        raise RuntimeError("Speech-Service lieferte kein Audio")
    return audio


def _to_wav(audio: bytes, directory: Path, stem: str) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg wurde nicht gefunden")
    source = directory / f".{stem}.input"
    target = directory / f"{stem}.wav"
    source.write_bytes(audio)
    process = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    source.unlink(missing_ok=True)
    if process.returncode != 0 or not target.is_file():
        raise RuntimeError("Audio-Konvertierung fehlgeschlagen: " + (process.stderr or "")[-1000:])
    return target.read_bytes()


def _read_pcm16_mono(wav_bytes: bytes) -> tuple[int, array]:
    with wave.open(io.BytesIO(wav_bytes), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise RuntimeError("Kalibrierungs-WAV ist nicht PCM16 mono")
        rate = handle.getframerate()
        pcm = handle.readframes(handle.getnframes())
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return rate, samples


def _dbfs(value: float) -> float | None:
    if value <= 0:
        return None
    return round(20.0 * math.log10(value / 32768.0), 2)


def _stats(wav_bytes: bytes) -> dict:
    rate, samples = _read_pcm16_mono(wav_bytes)
    count = len(samples)
    duration = count / rate if rate else 0.0
    if not count:
        return {
            "duration_seconds": 0.0,
            "active_duration_seconds": 0.0,
            "leading_silence_ms": 0.0,
            "trailing_silence_ms": 0.0,
            "peak_dbfs": None,
            "rms_dbfs": None,
            "active_rms_dbfs": None,
        }

    window = max(1, int(rate * WINDOW_MS / 1000.0))
    threshold = 32768.0 * (10.0 ** (SILENCE_DBFS / 20.0))

    def rms(start: int, end: int) -> float:
        n = max(1, end - start)
        return math.sqrt(
            sum(int(samples[i]) * int(samples[i]) for i in range(start, end)) / n
        )

    first_active = None
    last_active_end = None
    for start in range(0, count, window):
        end = min(count, start + window)
        if rms(start, end) > threshold:
            if first_active is None:
                first_active = start
            last_active_end = end

    peak = max(abs(int(sample)) for sample in samples)
    total_rms = math.sqrt(sum(int(s) * int(s) for s in samples) / count)

    if first_active is None or last_active_end is None:
        active_duration = 0.0
        leading_ms = duration * 1000.0
        trailing_ms = duration * 1000.0
        active_rms = None
    else:
        active_duration = (last_active_end - first_active) / rate
        leading_ms = first_active / rate * 1000.0
        trailing_ms = max(0.0, duration - last_active_end / rate) * 1000.0
        active_rms = rms(first_active, last_active_end)

    return {
        "sample_rate": rate,
        "duration_seconds": round(duration, 4),
        "active_duration_seconds": round(active_duration, 4),
        "leading_silence_ms": round(leading_ms, 1),
        "trailing_silence_ms": round(trailing_ms, 1),
        "peak_dbfs": _dbfs(peak),
        "rms_dbfs": _dbfs(total_rms),
        "active_rms_dbfs": _dbfs(active_rms or 0.0),
        "silence_threshold_dbfs": SILENCE_DBFS,
    }


def _slug(value: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in value).strip("-") or "voice"


def _render_candidate(
    base_url: str,
    out_dir: Path,
    text: str,
    language: str,
    voice: str | None,
    speed: float,
    label: str,
) -> dict:
    stem = f"{_slug(label)}-speed-{speed:.2f}"
    audio = _tts(base_url, text, language, voice, speed)
    wav = _to_wav(audio, out_dir, stem)
    stats = _stats(wav)
    return {
        "voice": voice,
        "label": label,
        "speed": speed,
        "wav": str(out_dir / f"{stem}.wav"),
        "stats": stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_SPEECH_URL)
    parser.add_argument("--language", default="de")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument(
        "--speeds",
        default=",".join(str(value) for value in DEFAULT_SPEEDS),
        help="Kommagetrennte TTS-Speed-Kandidaten, z.B. 1.0,0.9,0.8,0.7",
    )
    args = parser.parse_args()

    speeds = tuple(float(value.strip()) for value in args.speeds.split(",") if value.strip())
    if not speeds:
        raise SystemExit("Keine Speed-Kandidaten angegeben")

    manager = _http_json(args.url + "/v1/audio/voices/manage")
    voices = manager.get("voices") or []
    default_voice = manager.get("default")
    clones = [voice for voice in voices if voice.get("kind") == "clone"]
    if not clones:
        raise SystemExit("Keine Clone-Stimmen gefunden")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path.home() / ".config/mlx-web/talking-photo/calibration" / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Kalibrierung: {out_dir}")
    print(f"Standardstimme laut Voice-Manager: {default_voice or 'unbekannt'}")
    print(f"Text: {args.text}")
    print()

    # Important: baseline omits the voice field entirely, exactly like Talking Photo's
    # standard path. The manager's default id is recorded separately for diagnostics.
    baseline = _render_candidate(
        args.url,
        out_dir,
        args.text,
        args.language,
        None,
        1.0,
        "STANDARD",
    )
    baseline_active = baseline["stats"]["active_duration_seconds"]
    print(
        f"STANDARD: {baseline['stats']['duration_seconds']:.3f}s gesamt, "
        f"{baseline_active:.3f}s aktiv, "
        f"Start {baseline['stats']['leading_silence_ms']:.0f}ms"
    )

    results = []
    for voice in clones:
        voice_id = str(voice.get("id") or "").strip()
        if not voice_id:
            continue
        candidates = []
        for speed in speeds:
            candidate = _render_candidate(
                args.url,
                out_dir,
                args.text,
                args.language,
                voice_id,
                speed,
                voice_id,
            )
            active = candidate["stats"]["active_duration_seconds"]
            delta = active - baseline_active
            ratio = active / baseline_active if baseline_active else None
            candidate["active_delta_seconds_vs_standard"] = round(delta, 4)
            candidate["active_ratio_vs_standard"] = round(ratio, 4) if ratio is not None else None
            candidates.append(candidate)
            print(
                f"{voice_id:>10} speed={speed:.2f}: "
                f"{candidate['stats']['duration_seconds']:.3f}s gesamt, "
                f"{active:.3f}s aktiv, "
                f"Start {candidate['stats']['leading_silence_ms']:.0f}ms, "
                f"Delta {delta:+.3f}s"
            )

        closest = min(
            candidates,
            key=lambda item: abs(item["active_delta_seconds_vs_standard"]),
        )
        results.append(
            {
                "id": voice_id,
                "label": voice.get("label"),
                "kind": voice.get("kind"),
                "is_default": bool(voice.get("is_default")),
                "quality": voice.get("quality"),
                "sampling": voice.get("sampling"),
                "reference_duration_seconds": voice.get("duration_seconds"),
                "reference_size_bytes": voice.get("size_bytes"),
                "reference_transcript": voice.get("transcript"),
                "reference_chars_per_second": (
                    round(len(str(voice.get("transcript") or "")) / float(voice.get("duration_seconds")), 3)
                    if voice.get("duration_seconds")
                    else None
                ),
                "candidates": candidates,
                "closest_native_speed_by_active_duration": closest["speed"],
                "closest_native_speed_wav": closest["wav"],
                "note": (
                    "Duration matching is diagnostic only; do not auto-apply without a visual LTX lipsync test."
                ),
            }
        )
        print()

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "speech_service_url": args.url,
        "language": args.language,
        "text": args.text,
        "voice_manager_default": default_voice,
        "baseline": baseline,
        "voices": results,
    }
    report_path = out_dir / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("Fertig.")
    print(f"Report: {report_path}")
    print(f"WAVs:   {out_dir}")
    print()
    print("Wichtig: 'closest_native_speed' ist nur ein Kandidat, kein automatisch perfektes LTX-Profil.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
