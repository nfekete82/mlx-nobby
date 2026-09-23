#!/usr/bin/env python3

import base64
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def fail(message):
    print(message, file=sys.stderr, flush=True)
    raise SystemExit(1)


def validate_base_url(value):
    value = str(value or "").rstrip("/")
    parsed = urllib.parse.urlparse(value)

    if parsed.scheme != "http":
        fail("MLX-Serve muss lokal über HTTP angesprochen werden")

    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        fail("MLX-Serve darf nur über localhost angesprochen werden")

    if parsed.port is None:
        fail("MLX-Serve-Port fehlt")

    return value


def main():
    try:
        request_data = json.load(sys.stdin)
    except Exception:
        fail("Ungültige MLX-Serve-Worker-Anfrage")

    params = request_data.get("params") or {}
    output = Path(request_data["output"])
    repository = str(request_data["repository"])
    base_url = validate_base_url(request_data["base_url"])

    payload = {
        "model": repository,
        "prompt": str(params["prompt"]),
        "size": f'{int(params["width"])}x{int(params["height"])}',
        "steps": int(params["steps"]),
        "seed": int(params["seed"]),
    }

    guidance = params.get("guidance")
    if guidance is not None and float(guidance) > 0:
        payload["guidance_scale"] = float(guidance)

    negative_prompt = params.get("negative_prompt")
    if negative_prompt:
        payload["negative_prompt"] = str(negative_prompt)

    loras = request_data.get("loras") or []
    if not isinstance(loras, list):
        fail("Ungültige MLX-Serve-LoRA-Konfiguration")

    lora_paths = []
    lora_scales = []

    for lora in loras:
        if not isinstance(lora, dict):
            fail("Ungültige MLX-Serve-LoRA-Konfiguration")

        path = Path(str(lora.get("path") or ""))
        if (
            not path.is_absolute()
            or path.suffix.lower() != ".safetensors"
            or not path.is_file()
        ):
            fail("MLX-Serve-LoRA muss eine vorhandene absolute .safetensors-Datei sein")

        try:
            scale = float(lora.get("scale", 1.0))
        except (TypeError, ValueError):
            fail("Ungültiger MLX-Serve-LoRA-Scale")

        lora_paths.append(str(path))
        lora_scales.append(scale)

    if lora_paths:
        payload["lora_paths"] = lora_paths
        payload["lora_scales"] = lora_scales

    body = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        base_url + "/v1/images/generations",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=830) as response:
            if response.status != 200:
                fail(
                    f"MLX-Serve Bildgenerierung lieferte HTTP {response.status}"
                )
            raw = response.read()
    except urllib.error.HTTPError as exc:
        fail(f"MLX-Serve Bildgenerierung lieferte HTTP {exc.code}")
    except urllib.error.URLError:
        fail("MLX-Serve ist während der Bildgenerierung nicht erreichbar")
    except TimeoutError:
        fail("MLX-Serve Bildgenerierung hat das Zeitlimit überschritten")

    try:
        result = json.loads(raw.decode("utf-8"))
    except Exception:
        fail("MLX-Serve lieferte keine gültige JSON-Antwort")

    if result.get("error"):
        fail("MLX-Serve meldete einen Fehler bei der Bildgenerierung")

    images = result.get("data")
    if not isinstance(images, list) or not images:
        fail("MLX-Serve lieferte kein Bild")

    encoded = images[0].get("b64_json")
    if not encoded:
        fail("MLX-Serve lieferte keine Base64-Bilddaten")

    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except Exception:
        fail("MLX-Serve lieferte ungültige Base64-Bilddaten")

    output.parent.mkdir(parents=True, exist_ok=True)

    fd, temporary = tempfile.mkstemp(
        prefix=".mlxserve-image-",
        suffix=".png",
        dir=output.parent,
    )

    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(image_bytes)
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    main()
