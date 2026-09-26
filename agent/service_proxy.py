"""Fixed native service routes for Docker. No arbitrary URL/path forwarding."""
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

from backend import observability
from fastapi import HTTPException, Request
from fastapi.responses import Response


def forward(
    url,
    data=None,
    content_type="application/json",
    timeout=900,
    call_metrics=None,
    expose_metrics=False,
):
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": content_type},
        method="POST" if data is not None else "GET",
    )
    try:
        connect_started = time.monotonic()
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if call_metrics:
                call_metrics.set_upstream_connect(
                    (time.monotonic() - connect_started) * 1000
                )
            body = response.read()
            if call_metrics:
                try:
                    result = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    result = {}
                choices = result.get("choices") if isinstance(result, dict) else []
                choice = choices[0] if isinstance(choices, list) and choices else {}
                message = choice.get("message", {})
                call_metrics.finish(
                    usage=result.get("usage"),
                    output_text=(
                        message.get("content")
                        or message.get("reasoning")
                        or ""
                    ),
                    finish_reason=choice.get("finish_reason"),
                )
                if expose_metrics and isinstance(result, dict):
                    result["_mlx_metrics"] = observability.trace_snapshot(
                        call_metrics.trace_id
                    )
                    body = json.dumps(
                        result,
                        ensure_ascii=False,
                    ).encode("utf-8")
            return Response(body, status_code=response.status,
                            media_type=response.headers.get_content_type())
    except urllib.error.HTTPError as exc:
        if call_metrics:
            call_metrics.fail("http_error")
        return Response(exc.read(), status_code=exc.code,
                        media_type=exc.headers.get_content_type())
    except (urllib.error.URLError, TimeoutError) as exc:
        if call_metrics:
            call_metrics.fail(type(exc).__name__)
        raise HTTPException(503, "Nativer Dienst ist nicht erreichbar") from exc
    except Exception as exc:
        if call_metrics:
            call_metrics.fail(type(exc).__name__)
        raise


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _quantization_label(config, model_path):
    quant = config.get("quantization")
    if isinstance(quant, dict):
        bits = quant.get("bits")
        if bits:
            return f"{bits}-bit"
    quant = config.get("quantization_config")
    if isinstance(quant, dict):
        bits = quant.get("bits") or quant.get("nbits")
        if bits:
            return f"{bits}-bit"
    name = model_path.name.lower()
    for bits in (2, 3, 4, 5, 6, 8):
        if f"{bits}-bit" in name or f"{bits}bit" in name:
            return f"{bits}-bit"
    return None


def _looks_like_vision_model(config, model_path):
    searchable = " ".join([
        str(config.get("model_type", "")),
        " ".join(str(item) for item in config.get("architectures", []) if item),
    ]).lower()
    vision_markers = ("vl", "vision", "multimodal", "conditionalgeneration")
    config_vision = any(marker in searchable for marker in vision_markers)
    processor_files = any(
        (model_path / filename).exists()
        for filename in (
            "processor_config.json",
            "preprocessor_config.json",
            "video_preprocessor_config.json",
        )
    )
    return config_vision or processor_files


def _validate_local_model_path(raw_path):
    raw = str(raw_path or "").strip()
    if not raw:
        return {
            "valid": False,
            "local": True,
            "checks": [{"key": "path", "ok": False, "label": "Pfad fehlt"}],
            "errors": ["Pfad fehlt"],
        }

    model_path = Path(os.path.expanduser(raw)).resolve()
    checks = []
    errors = []

    exists = model_path.exists()
    checks.append({"key": "exists", "ok": exists, "label": "Pfad vorhanden"})
    if not exists:
        errors.append("Der angegebene Pfad existiert nicht.")
        return {
            "valid": False,
            "local": True,
            "path": str(model_path),
            "checks": checks,
            "errors": errors,
        }

    is_directory = model_path.is_dir()
    checks.append({"key": "directory", "ok": is_directory, "label": "Verzeichnis"})
    if not is_directory:
        errors.append("Der angegebene Pfad ist kein Verzeichnis.")
        return {
            "valid": False,
            "local": True,
            "path": str(model_path),
            "checks": checks,
            "errors": errors,
        }

    config_path = model_path / "config.json"
    config_exists = config_path.is_file()
    checks.append({"key": "config", "ok": config_exists, "label": "config.json"})
    config = _read_json(config_path) if config_exists else None
    config_valid = isinstance(config, dict)
    checks.append({"key": "config_valid", "ok": config_valid, "label": "Konfiguration lesbar"})
    if not config_exists:
        errors.append("config.json fehlt.")
    elif not config_valid:
        errors.append("config.json ist ungültig oder nicht lesbar.")
        config = {}

    weights = sorted(model_path.glob("*.safetensors"))
    has_weights = bool(weights)
    checks.append({"key": "weights", "ok": has_weights, "label": "Safetensors-Gewichte"})
    if not has_weights:
        errors.append("Keine .safetensors-Gewichte gefunden.")

    tokenizer_candidates = (
        "tokenizer.json",
        "tokenizer_config.json",
        "sentencepiece.bpe.model",
        "tokenizer.model",
    )
    has_tokenizer = any((model_path / item).exists() for item in tokenizer_candidates)
    checks.append({"key": "tokenizer", "ok": has_tokenizer, "label": "Tokenizer"})
    if not has_tokenizer:
        errors.append("Kein Tokenizer erkannt.")

    model_type = str(config.get("model_type") or "").strip() or None
    architectures = config.get("architectures")
    architecture = None
    if isinstance(architectures, list) and architectures:
        architecture = str(architectures[0])

    quantization = _quantization_label(config, model_path)
    vision = _looks_like_vision_model(config, model_path)
    backend = "vlm" if vision else "llm"

    mlx_quant = isinstance(config.get("quantization"), dict)
    checks.append({
        "key": "mlx",
        "ok": config_valid and has_weights,
        "label": "MLX-Struktur erkannt" if mlx_quant else "Modellstruktur erkannt",
    })

    size_bytes = 0
    try:
        size_bytes = sum(file.stat().st_size for file in weights)
    except OSError:
        size_bytes = 0

    valid = config_valid and has_weights and has_tokenizer
    return {
        "valid": valid,
        "local": True,
        "path": str(model_path),
        "checks": checks,
        "errors": errors,
        "detected": {
            "model_type": model_type,
            "architecture": architecture,
            "backend": backend,
            "vision": vision,
            "quantization": quantization,
            "weight_files": len(weights),
            "size_bytes": size_bytes,
        },
    }


def install_routes(app, runtime_port, runtime_lock):
    @app.get("/api/bridge/mlx/v1/models")
    def models():
        return forward(f"http://127.0.0.1:{runtime_port()}/v1/models", timeout=10)

    @app.post("/api/models/validate-local")
    def validate_local_model(payload: dict):
        path = payload.get("path") if isinstance(payload, dict) else None
        return _validate_local_model_path(path)

    @app.post("/api/bridge/mlx/v1/chat/completions")
    def chat(payload: dict):
        # These existing callers return a single response; role-aware streaming
        # continues to use /api/runtime/chat/stream.
        if payload.get("stream"):
            raise HTTPException(422, "Streaming benötigt /api/runtime/chat/stream")
        trace_data = payload.pop("_mlx_observability", {})
        trace_data = trace_data if isinstance(trace_data, dict) else {}
        expose_metrics = bool(trace_data)
        call_metrics = observability.ModelCallMetrics(
            trace_id=trace_data.get("trace_id"),
            parent_request_id=trace_data.get("parent_request_id"),
            purpose=trace_data.get("purpose") or "chat.nonstream",
            model=payload.get("model"),
            role=trace_data.get("role"),
            backend=trace_data.get("backend"),
            messages=payload.get("messages"),
            context_sources=trace_data.get("context_sources"),
        )
        wait_started = time.monotonic()
        with runtime_lock:
            call_metrics.set_queue_wait(
                (time.monotonic() - wait_started) * 1000
            )
            return forward(f"http://127.0.0.1:{runtime_port()}/v1/chat/completions",
                           json.dumps(payload).encode("utf-8"),
                           call_metrics=call_metrics,
                           expose_metrics=expose_metrics)

    @app.post("/api/bridge/speech/v1/audio/transcriptions")
    async def speech(request: Request):
        content_type = request.headers.get("content-type", "")
        if not content_type.lower().startswith("multipart/form-data;"):
            raise HTTPException(415, "Multipart-Audiodatei erwartet")
        data = await request.body()  # LocalRequestGuard bounds the raw stream.
        url = os.environ.get("SPEECH_SERVICE_URL", "http://127.0.0.1:8050").rstrip("/")
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(forward, url + "/v1/audio/transcriptions", data, content_type, 180)
