"""PCM diagnostics for Talking Photo; never changes timing or sample values."""
from array import array
import io
import math
import sys
import wave

_AUDIO_SILENCE_DBFS = -45.0
_AUDIO_WINDOW_MS = 10.0


def _dbfs(value: float) -> float | None:
    if value <= 0:
        return None
    return round(20.0 * math.log10(value / 32768.0), 2)


def _read_pcm16_mono(wav_bytes: bytes) -> tuple[int, array]:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            frame_count = handle.getnframes()
            pcm = handle.readframes(frame_count)
    except (wave.Error, EOFError) as exc:
        raise RuntimeError("Talking-Photo-WAV konnte nicht analysiert werden") from exc

    if channels != 1 or sample_width != 2:
        raise RuntimeError(
            f"Unerwartetes Talking-Photo-WAV: {channels} Kanal/Kanäle, {sample_width * 8} Bit"
        )
    if len(pcm) != frame_count * channels * sample_width:
        raise RuntimeError("Talking-Photo-WAV ist abgeschnitten")

    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return sample_rate, samples


def _analyze_wav(wav_bytes: bytes) -> dict:
    """Measure the exact 16 kHz mono WAV passed to LTX."""
    sample_rate, samples = _read_pcm16_mono(wav_bytes)
    frame_count = len(samples)
    total_samples = len(samples)
    duration = total_samples / sample_rate if sample_rate else 0.0
    if not total_samples:
        return {
            "sample_rate": sample_rate,
            "channels": 1,
            "sample_width_bytes": 2,
            "frames": frame_count,
            "duration_seconds": 0.0,
            "peak_dbfs": None,
            "rms_dbfs": None,
            "active_rms_dbfs": None,
            "active_audio_fraction": 0.0,
            "leading_silence_ms": 0.0,
            "trailing_silence_ms": 0.0,
            "silence_threshold_dbfs": _AUDIO_SILENCE_DBFS,
        }

    peak = max(abs(int(sample)) for sample in samples)
    rms = math.sqrt(sum(int(sample) * int(sample) for sample in samples) / total_samples)

    window = max(1, int(sample_rate * (_AUDIO_WINDOW_MS / 1000.0)))
    threshold = 32768.0 * (10.0 ** (_AUDIO_SILENCE_DBFS / 20.0))

    def window_rms(start: int, end: int) -> float:
        count = max(1, end - start)
        return math.sqrt(
            sum(int(samples[index]) * int(samples[index]) for index in range(start, end)) / count
        )

    first_active = None
    last_active_end = None
    active_samples = 0
    for start in range(0, total_samples, window):
        end = min(total_samples, start + window)
        if window_rms(start, end) > threshold:
            active_samples += end - start
            if first_active is None:
                first_active = start
            last_active_end = end

    if first_active is None or last_active_end is None:
        leading_ms = duration * 1000.0
        trailing_ms = duration * 1000.0
        active_rms = None
    else:
        leading_ms = (first_active / sample_rate) * 1000.0
        trailing_ms = max(0.0, duration - (last_active_end / sample_rate)) * 1000.0
        active_count = max(1, last_active_end - first_active)
        active_rms_value = math.sqrt(
            sum(
                int(samples[index]) * int(samples[index])
                for index in range(first_active, last_active_end)
            )
            / active_count
        )
        active_rms = _dbfs(active_rms_value)

    return {
        "sample_rate": sample_rate,
        "channels": 1,
        "sample_width_bytes": 2,
        "frames": frame_count,
        "duration_seconds": round(duration, 4),
        "peak_dbfs": _dbfs(peak),
        "rms_dbfs": _dbfs(rms),
        "active_rms_dbfs": active_rms,
        "active_audio_fraction": round(active_samples / total_samples, 4),
        "leading_silence_ms": round(leading_ms, 1),
        "trailing_silence_ms": round(trailing_ms, 1),
        "silence_threshold_dbfs": _AUDIO_SILENCE_DBFS,
    }


def prepend_lead_in(wav_bytes: bytes, lead_in_ms: int = 0) -> bytes:
    """Opt-in silence before speech; preserve every original PCM sample.

    The same returned WAV must be used for both LTX conditioning and final
    playback. A positive lead-in is deliberately restricted to the 500-ms
    experiment; normal jobs remain bit-for-bit unchanged.
    """
    if type(lead_in_ms) is not int or lead_in_ms not in (0, 500):
        raise ValueError("Talking-Photo-Audiovorlauf muss 0 oder 500 ms betragen")
    if lead_in_ms == 0:
        return wav_bytes
    stats = validate_wav(wav_bytes)
    with wave.open(io.BytesIO(wav_bytes), "rb") as source:
        frames = source.readframes(source.getnframes())
    silence = bytes(2 * (stats["sample_rate"] * lead_in_ms // 1000))
    target = io.BytesIO()
    with wave.open(target, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(stats["sample_rate"])
        output.writeframes(silence + frames)
    return target.getvalue()


def validate_wav(wav_bytes: bytes) -> dict:
    stats = _analyze_wav(wav_bytes)
    if stats["sample_rate"] != 16000:
        raise RuntimeError("LTX-Audio muss 16000 Hz haben")
    if not stats["frames"]:
        raise RuntimeError("LTX-Audio ist leer")
    if stats["active_rms_dbfs"] is None:
        raise RuntimeError("LTX-Audio enthält kein aktives Audiosignal oberhalb -45 dBFS")
    return stats
