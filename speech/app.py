from pathlib import Path
import os
import subprocess
import tempfile
import threading
import shutil

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from mlx_audio.stt import load
from mlx_audio.tts.utils import load_model as load_tts_model
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

TTS_MODEL_NAME = os.environ.get(
    "MLX_TTS_MODEL",
    "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-6bit",
)

TTS_DEFAULT_VOICE = os.environ.get(
    "MLX_TTS_VOICE",
    "Serena",
)

TTS_DEFAULT_LANGUAGE = os.environ.get(
    "MLX_TTS_LANGUAGE",
    "de",
)

TTS_DEFAULT_INSTRUCT = os.environ.get(
    "MLX_TTS_INSTRUCT",
    (
        "Speak in a warm, soft, feminine and natural voice. "
        "Calm, friendly and slightly playful."
    ),
)

_tts_model = None
_tts_model_lock = threading.Lock()


class SpeechRequest(BaseModel):
    input: str
    voice: str = TTS_DEFAULT_VOICE
    language: str = TTS_DEFAULT_LANGUAGE
    instruct: str = TTS_DEFAULT_INSTRUCT
    speed: float = 1.0


def get_model():
    global _model

    if _model is None:
        with _model_lock:
            if _model is None:
                print(f"[speech] Lade Modell: {MODEL_NAME}", flush=True)
                _model = load(MODEL_NAME)
                print("[speech] Modell bereit", flush=True)

    return _model


def get_tts_model():
    global _tts_model

    if _tts_model is None:
        with _tts_model_lock:
            if _tts_model is None:
                print(
                    f"[speech] Lade TTS-Modell: {TTS_MODEL_NAME}",
                    flush=True,
                )
                _tts_model = load_tts_model(TTS_MODEL_NAME)
                print(
                    "[speech] TTS-Modell bereit",
                    flush=True,
                )

    return _tts_model


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "loaded": _model is not None,
        "tts_model": TTS_MODEL_NAME,
        "tts_loaded": _tts_model is not None,
        "tts_voice": TTS_DEFAULT_VOICE,
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


@app.post("/v1/audio/speech")
def synthesize_speech(request: SpeechRequest):
    text = request.input.strip()

    if not text:
        raise HTTPException(
            status_code=400,
            detail="Leerer Text",
        )

    if len(text) > 20000:
        raise HTTPException(
            status_code=413,
            detail="Text zu lang",
        )

    if not 0.5 <= request.speed <= 2.0:
        raise HTTPException(
            status_code=400,
            detail="Ungültige Geschwindigkeit",
        )

    wav_path = None

    try:
        model = get_tts_model()

        results = list(
            model.generate_custom_voice(
                text=text,
                speaker=request.voice,
                language=request.language,
                instruct=request.instruct,
            )
        )

        if not results:
            raise RuntimeError(
                "TTS hat keine Audiodaten erzeugt"
            )

        result = results[0]
        audio = result.audio

        with tempfile.NamedTemporaryFile(
            suffix=".wav",
            delete=False,
        ) as tmp:
            wav_path = tmp.name

        import soundfile as sf

        sample_rate = getattr(
            result,
            "sample_rate",
            None,
        )

        if not sample_rate:
            sample_rate = getattr(
                model,
                "sample_rate",
                24000,
            )

        if hasattr(audio, "tolist"):
            audio = audio.tolist()

        sf.write(
            wav_path,
            audio,
            sample_rate,
        )

        process = subprocess.run(
            [
                FFMPEG,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                wav_path,
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "192k",
                "-f",
                "mp3",
                "pipe:1",
            ],
            capture_output=True,
            timeout=120,
        )

        if process.returncode != 0:
            error = process.stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()

            raise RuntimeError(
                "MP3-Konvertierung fehlgeschlagen: "
                + error
            )

        if not process.stdout:
            raise RuntimeError(
                "Leere MP3-Ausgabe"
            )

        return Response(
            content=process.stdout,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition":
                    'inline; filename="mlx-nobby-speech.mp3"',
                "Cache-Control": "no-store",
            },
        )

    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "MP3-Konvertierung hat "
                "zu lange gedauert"
            ),
        ) from exc

    except HTTPException:
        raise

    except Exception as exc:
        print(
            f"[speech] TTS-Fehler: {exc!r}",
            flush=True,
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    finally:
        if wav_path:
            try:
                os.unlink(wav_path)
            except FileNotFoundError:
                pass
