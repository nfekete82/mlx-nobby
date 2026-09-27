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


def job_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{24}", value):
        raise HTTPException(422, "Ungültige Image-Job-ID")
    return value


def _raw_request(method, path, payload=None, timeout=10):
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


def request(method, path, payload=None, timeout=10):
    """Use the durable Agent queue for asynchronous image jobs.

    Direct model/health/synchronous endpoints keep going straight to the native
    service. Existing callers therefore keep the same API shape while multiple
    async media requests can wait instead of receiving a 409 conflict.
    """
    if path.startswith("/jobs"):
        from agent import media_queue

        if method == "POST" and path == "/jobs":
            return media_queue.enqueue("image", payload)

        match = re.fullmatch(r"/jobs/([a-f0-9]{24})", path)
        if method == "GET" and match:
            queued = media_queue.get_job("image", match.group(1))
            if queued is not None:
                return queued

        match = re.fullmatch(r"/jobs/([a-f0-9]{24})/cancel", path)
        if method == "POST" and match:
            queued = media_queue.cancel("image", match.group(1))
            if queued is not None:
                return queued

        if method == "POST" and path == "/jobs/cancel-chat":
            request_data = payload if isinstance(payload, dict) else {}
            queued = media_queue.cancel_chat(
                "image",
                request_data.get("chat_id"),
                request_data.get("chat_revision"),
            )
            native = _raw_request(method, path, payload, timeout)
            existing = native.get("cancelled") if isinstance(native, dict) else []
            existing = existing if isinstance(existing, list) else []
            if isinstance(native, dict):
                native["cancelled"] = queued + existing
                native["cancelled_count"] = len(native["cancelled"])
                return native

    return _raw_request(method, path, payload, timeout)
