"""Native agent bridge to the single image service."""
import json
import os
import re
import socket
import urllib.error
import urllib.request
from fastapi import HTTPException

IMAGE_URL = os.environ.get("IMAGE_SERVICE_URL", "http://127.0.0.1:8030").rstrip("/")


def model_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value):
        raise HTTPException(422, "Ungültige Image-Modell-ID")
    return value


def request(method, path, payload=None, timeout=10):
    req = urllib.request.Request(IMAGE_URL + path, method=method,
                                 data=json.dumps(payload).encode() if payload is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail", "Image-Service-Fehler")
        except ValueError:
            detail = "Image-Service-Fehler"
        raise HTTPException(exc.code, detail) from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise HTTPException(503, "Image-Service nicht erreichbar oder Zeitlimit überschritten") from exc
