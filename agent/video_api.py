"""Agent bridge to the local video service."""
import json
import os
import re
import socket
import urllib.error
import urllib.request

from fastapi import HTTPException


VIDEO_URL = os.environ.get("VIDEO_SERVICE_URL", "http://127.0.0.1:8060").rstrip("/")


def job_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{24}", value):
        raise HTTPException(422, "Ungültige Video-Job-ID")
    return value


def _raw_request(method, path, payload=None, timeout=15):
    req = urllib.request.Request(
        VIDEO_URL + path,
        method=method,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail", "Video-Service-Fehler")
        except ValueError:
            detail = "Video-Service-Fehler"
        raise HTTPException(exc.code, detail) from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise HTTPException(503, "Video-Service nicht erreichbar") from exc


def request(method, path, payload=None, timeout=15):
    """Route asynchronous video jobs through the Agent-owned media queue."""
    if path.startswith("/jobs"):
        from agent import media_queue

        if method == "POST" and path == "/jobs":
            return media_queue.enqueue("video", payload)

        match = re.fullmatch(r"/jobs/([a-f0-9]{24})", path)
        if method == "GET" and match:
            queued = media_queue.get_job("video", match.group(1))
            if queued is not None:
                return queued

        match = re.fullmatch(r"/jobs/([a-f0-9]{24})/cancel", path)
        if method == "POST" and match:
            queued = media_queue.cancel("video", match.group(1))
            if queued is not None:
                return queued

    return _raw_request(method, path, payload, timeout)
