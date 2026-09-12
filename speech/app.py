from pathlib import Path
import os
import subprocess
import tempfile
import threading
import shutil

from fastapi import FastAPI, File, HTTPException, UploadFile
from mlx_audio.stt import load
from local_security import LocalRequestGuard, read_upload


MODEL_NAME = os.environ.get(
    "MLX_SPEECH_MODEL",
    "mlx-community/whisper-large-v3-turbo-asr-fp16",
)

FFMPEG = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
MAX_AUDIO_BYTES = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "250")) * 1024**2

app = FastAPI(title="MLX nobby Speech")
app.add_middleware(LocalRequestGuard)

_model = None
_model_lock = threading.Lock()


def get_model():
    global _model

    if _model is None:
        with _model_lock:
            if _model is None:
                print(f"[speech] Lade Modell: {MODEL_NAME}", flush=True)
                _model = load(MODEL_NAME)
                print("[speech] Modell bereit", flush=True)

    return _model


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "loaded": _model is not None,
    }


@app.post("/v1/audio/transcriptions")
async def transcribe(file: UploadFile = File(...)):
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"

    if suffix.lower() not in {".webm", ".wav", ".mp3", ".mp4", ".m4a", ".ogg", ".oga", ".flac", ".aac"}:
        raise HTTPException(415, "Nicht unterstütztes Audioformat")
    data = await read_upload(file, MAX_AUDIO_BYTES)

    if not data:
        raise HTTPException(status_code=400, detail="Leere Audiodatei")

    source_path = None
    wav_path = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=suffix,
            delete=False,
        ) as tmp:
            tmp.write(data)
            source_path = tmp.name

        with tempfile.NamedTemporaryFile(
            suffix=".wav",
            delete=False,
        ) as tmp:
            wav_path = tmp.name

        # Reliably normalize browser audio to the format expected by Whisper.
        process = subprocess.run(
            [
                FFMPEG,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                source_path,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                wav_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if process.returncode != 0:
            raise RuntimeError(
                f"Audio-Konvertierung fehlgeschlagen: {process.stderr.strip()}"
            )

        model = get_model()
        result = model.generate(wav_path)

        if isinstance(result, str):
            text = result
        elif hasattr(result, "text"):
            text = result.text
        elif isinstance(result, dict):
            text = result.get("text", "")
        else:
            text = str(result)

        return {
            "text": text.strip(),
            "model": MODEL_NAME,
        }

    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=500,
            detail="Audio-Konvertierung hat zu lange gedauert",
        ) from exc

    except Exception as exc:
        print(f"[speech] Fehler: {exc!r}", flush=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    finally:
        for path in (source_path, wav_path):
            if path:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
