"""Deterministic serialization and handoff for heavy local runtimes."""

import fcntl
import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.parse
from contextlib import contextmanager
from pathlib import Path


IMAGE_URL = os.environ.get(
    "IMAGE_SERVICE_URL", "http://127.0.0.1:8030"
).rstrip("/")
VIDEO_URL = os.environ.get(
    "VIDEO_SERVICE_URL", "http://127.0.0.1:8060"
).rstrip("/")
LOCK_PATH = Path(os.environ.get(
    "MLX_RUNTIME_COORDINATOR_LOCK",
    f"/tmp/mlx-web-runtime-{os.getuid()}.lock",
))
POLL_INTERVAL = 0.2
_PROCESS_LOCK = threading.RLock()
_LEASE_STATE = threading.local()


class CoordinationCancelled(RuntimeError):
    """Raised when a queued handoff is cancelled by its owning job."""


class ServiceUnavailable(RuntimeError):
    """Raised when coordinator state cannot be read from a local service."""


def _cancelled(cancel_event):
    return cancel_event is not None and cancel_event.is_set()


def _check_cancelled(cancel_event):
    if _cancelled(cancel_event):
        raise CoordinationCancelled("Runtime handoff was cancelled")


def request_json(method, url, payload=None, timeout=10):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {
        "127.0.0.1", "localhost", "::1",
    }:
        raise ValueError("Runtime coordinator only accepts local HTTP services")
    connection = http.client.HTTPConnection(
        parsed.hostname,
        parsed.port,
        timeout=timeout,
    )
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    try:
        connection.request(
            method,
            parsed.path or "/",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        response = connection.getresponse()
        raw = response.read()
        if response.status >= 400:
            raise RuntimeError(
                f"Runtime service returned HTTP {response.status}"
            )
        return json.loads(raw.decode("utf-8"))
    finally:
        connection.close()


@contextmanager
def runtime_lease(cancel_event=None, *, lock_path=LOCK_PATH):
    """Hold the cross-service heavy-runtime lease, waiting cancellably."""
    while not _PROCESS_LOCK.acquire(timeout=POLL_INTERVAL):
        _check_cancelled(cancel_event)
    depth = getattr(_LEASE_STATE, "depth", 0)
    if depth:
        _LEASE_STATE.depth = depth + 1
        try:
            yield
        finally:
            _LEASE_STATE.depth -= 1
            _PROCESS_LOCK.release()
        return

    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as handle:
            while True:
                _check_cancelled(cancel_event)
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(POLL_INTERVAL)
            _LEASE_STATE.depth = 1
            try:
                yield
            finally:
                _LEASE_STATE.depth = 0
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        _PROCESS_LOCK.release()


def _generation_active(health):
    if "active_generation" in health:
        return health.get("active_generation") is True
    return health.get("status") == "busy"


def wait_for_idle(service_url, service_name, cancel_event=None, *, requester=request_json):
    """Wait for real service-reported generation state without cancelling it."""
    while True:
        _check_cancelled(cancel_event)
        try:
            health = requester("GET", service_url + "/health", timeout=10)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise ServiceUnavailable(
                f"{service_name}-Service-Zustand konnte nicht geprüft werden"
            ) from exc
        if not _generation_active(health):
            return health
        time.sleep(POLL_INTERVAL)


def release_idle_image_runtime(cancel_event=None, *, requester=request_json):
    """Wait for image work, then unload only a resident idle image runtime."""
    health = wait_for_idle(
        IMAGE_URL, "Image", cancel_event, requester=requester
    )
    _check_cancelled(cancel_event)
    if health.get("loaded"):
        requester("POST", IMAGE_URL + "/unload", {}, timeout=120)
        health = wait_for_idle(
            IMAGE_URL, "Image", cancel_event, requester=requester
        )
        if health.get("loaded"):
            raise RuntimeError("Image-Runtime konnte nicht entladen werden")
    return health


@contextmanager
def video_runtime(
    cancel_event,
    *,
    chat_loaded,
    chat_command,
    restore_error=None,
    requester=request_json,
    lock_path=LOCK_PATH,
):
    """Hand off image/chat resources to video and restore prior chat state."""
    with runtime_lease(cancel_event, lock_path=lock_path):
        release_idle_image_runtime(cancel_event, requester=requester)
        _check_cancelled(cancel_event)
        restore_chat = chat_loaded()
        if restore_chat:
            chat_command("stop")
        try:
            _check_cancelled(cancel_event)
            yield
        finally:
            if restore_chat:
                try:
                    chat_command("start")
                except Exception as exc:
                    if restore_error is None:
                        raise
                    restore_error(exc)


@contextmanager
def image_runtime(cancel_event, *, requester=request_json, lock_path=LOCK_PATH):
    """Wait for active video work and serialize image/video generation."""
    with runtime_lease(cancel_event, lock_path=lock_path):
        wait_for_idle(VIDEO_URL, "Video", cancel_event, requester=requester)
        _check_cancelled(cancel_event)
        yield


def prepare_chat_runtime(*, requester=request_json, lock_path=LOCK_PATH):
    """Release an idle image runtime before the shared chat runtime starts."""
    with chat_runtime(requester=requester, lock_path=lock_path):
        return {"ok": True}


@contextmanager
def chat_runtime(
    cancel_event=None, *, requester=request_json, lock_path=LOCK_PATH
):
    """Hold the heavy-runtime lease for a chat request."""
    already_coordinated = getattr(_LEASE_STATE, "depth", 0) > 0
    with runtime_lease(cancel_event, lock_path=lock_path):
        if not already_coordinated:
            try:
                release_idle_image_runtime(cancel_event, requester=requester)
            except ServiceUnavailable:
                # Preserve chat availability when the optional image service
                # is offline. The cross-process lease still excludes any
                # coordinated active generation.
                pass
        _check_cancelled(cancel_event)
        yield
