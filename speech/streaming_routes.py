"""Low-latency PCM streaming for interactive chat TTS.

The existing /v1/audio/speech MP3 endpoint intentionally remains untouched for
Shorts, downloads and non-1.0 playback speeds. This route emits newline-delimited
JSON with base64 encoded mono float32 PCM chunks as soon as Qwen3-TTS yields them.
"""

from __future__ import annotations

from array import array
import base64
import json
import os
import sys
import threading
import time

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from speech.app import (
    SpeechRequest,
    get_tts_clone_model,
    get_tts_model,
    get_voice_profile,
    list_voice_profiles,
)


_STREAM_INTERVAL = min(
    2.0,
    max(0.16, float(os.environ.get("MLX_TTS_STREAM_INTERVAL", "0.32"))),
)
_PRELOAD_MODE = os.environ.get("MLX_TTS_PRELOAD", "auto").strip().lower()
_PRELOAD_STATE = {
    "mode": _PRELOAD_MODE,
    "status": "idle",
    "started_at": None,
    "ready_at": None,
    "error": None,
}
_PRELOAD_LOCK = threading.Lock()
_PRELOAD_STARTED = False


def _pcm_bytes(audio) -> bytes:
    if hasattr(audio, "tolist"):
        audio = audio.tolist()
    samples = array("f", (float(value) for value in audio))
    if samples.itemsize != 4:
        raise RuntimeError("Float32 PCM is not supported on this Python build")
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def _json_line(payload: dict) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


def _stream_results(request: SpeechRequest):
    text = request.input.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Leerer Text")
    if len(text) > 20000:
        raise HTTPException(status_code=413, detail="Text zu lang")
    if abs(float(request.speed) - 1.0) > 1e-6:
        raise HTTPException(
            status_code=409,
            detail="Streaming ist aktuell nur mit Geschwindigkeit 1.0 verfügbar",
        )

    profile = get_voice_profile(request.voice)
    if profile is not None:
        model = get_tts_clone_model()
        results = model.generate(
            text=text,
            ref_audio=str(profile["reference"]),
            ref_text=profile["ref_text"],
            stream=True,
            streaming_interval=_STREAM_INTERVAL,
        )
    else:
        model = get_tts_model()
        results = model.generate_custom_voice(
            text=text,
            speaker=request.voice,
            language=request.language,
            instruct=request.instruct,
            stream=True,
            streaming_interval=_STREAM_INTERVAL,
        )

    started = time.perf_counter()
    chunks = 0
    yield _json_line(
        {
            "type": "start",
            "voice": request.voice,
            "format": "f32le",
            "channels": 1,
            "streaming_interval": _STREAM_INTERVAL,
        }
    )

    try:
        for result in results:
            pcm = _pcm_bytes(result.audio)
            if not pcm:
                continue
            chunks += 1
            yield _json_line(
                {
                    "type": "audio",
                    "index": chunks - 1,
                    "sample_rate": int(getattr(result, "sample_rate", 24000) or 24000),
                    "pcm": base64.b64encode(pcm).decode("ascii"),
                }
            )
    except GeneratorExit:
        raise
    except Exception as exc:
        yield _json_line({"type": "error", "detail": str(exc)})
        return

    yield _json_line(
        {
            "type": "done",
            "chunks": chunks,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        }
    )


def _preload_worker():
    mode = _PRELOAD_MODE
    if mode in {"", "0", "false", "off", "none"}:
        _PRELOAD_STATE["status"] = "disabled"
        return

    if mode == "auto":
        mode = "clone" if list_voice_profiles() else "preset"

    _PRELOAD_STATE.update(
        {
            "mode": mode,
            "status": "loading",
            "started_at": time.time(),
            "ready_at": None,
            "error": None,
        }
    )
    try:
        if mode == "clone":
            get_tts_clone_model()
        elif mode in {"preset", "custom"}:
            get_tts_model()
        else:
            raise ValueError(f"Unbekannter MLX_TTS_PRELOAD-Modus: {mode}")
        _PRELOAD_STATE["status"] = "ready"
        _PRELOAD_STATE["ready_at"] = time.time()
        print(f"[speech] TTS-Warmup bereit ({mode})", flush=True)
    except Exception as exc:
        _PRELOAD_STATE["status"] = "failed"
        _PRELOAD_STATE["error"] = str(exc)
        print(f"[speech] TTS-Warmup fehlgeschlagen: {exc!r}", flush=True)


def start_preload_once():
    global _PRELOAD_STARTED
    with _PRELOAD_LOCK:
        if _PRELOAD_STARTED:
            return
        _PRELOAD_STARTED = True
    threading.Thread(
        target=_preload_worker,
        name="mlx-tts-preload",
        daemon=True,
    ).start()


def install_routes(app):
    route_paths = {getattr(route, "path", None) for route in app.routes}

    if "/v1/audio/speech/stream" not in route_paths:
        @app.post("/v1/audio/speech/stream")
        def stream_speech(request: SpeechRequest):
            # Validate before response headers are sent so client errors still use
            # normal HTTP status codes.
            text = request.input.strip()
            if not text:
                raise HTTPException(status_code=400, detail="Leerer Text")
            if len(text) > 20000:
                raise HTTPException(status_code=413, detail="Text zu lang")
            if abs(float(request.speed) - 1.0) > 1e-6:
                raise HTTPException(
                    status_code=409,
                    detail="Streaming ist aktuell nur mit Geschwindigkeit 1.0 verfügbar",
                )
            return StreamingResponse(
                _stream_results(request),
                media_type="application/x-ndjson",
                headers={
                    "Cache-Control": "no-store",
                    "X-Accel-Buffering": "no",
                },
            )

    if "/v1/audio/speech/stream/status" not in route_paths:
        @app.get("/v1/audio/speech/stream/status")
        def stream_status():
            return {
                **_PRELOAD_STATE,
                "streaming_interval": _STREAM_INTERVAL,
            }

    if not getattr(app.state, "mlx_tts_preload_hook", False):
        app.state.mlx_tts_preload_hook = True

        @app.on_event("startup")
        def preload_tts_on_startup():
            start_preload_once()
