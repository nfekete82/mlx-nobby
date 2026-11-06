"""Lightweight, opt-in port-8040 gateway to the supervised port-8011 Qwen 4B.

This process never loads a checkpoint. The *same* dedicated 4B handles router
inference and memory extraction; demand is signaled to its existing supervisor.
Media takes precedence through the cross-process runtime lease. No prompts,
responses, or personal data are persisted in gateway logs.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request

import runtime_coordinator as rc
from agent import memory_model_coordination as ctl
from agent import memory_model_supervisor as supervisor

HOST = "127.0.0.1"
PORT = 8040
UPSTREAM = "http://127.0.0.1:8011"
MAX_REQUEST = 1_000_000
MAX_RESPONSE = 3_000_000
COLD_START_TIMEOUT = 120
_GATE = threading.Lock()
_ACTIVE = 0
_ACTIVE_LOCK = threading.Lock()


class RouterUnavailable(RuntimeError):
    pass


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), _NoRedirects()
)


def _active():
    with _ACTIVE_LOCK:
        return _ACTIVE


def health():
    return {
        "ok": True,
        "status": "busy" if _active() else "ready",
        "router_manager": "shared-4b",
        "model_manager_version": 1,
        # Gateway carries NO model weights; the separate supervised 8011
        # is preempted by the existing protected media/Memory handoff.
        "loaded": False,
        "shared_model_loaded": (
            ctl.supervisor_state().get("owned") is True
            and ctl.supervisor_state().get("state") == "running"
        ),
        "active_generation": _active() > 0,
    }


def _ready():
    state = ctl.supervisor_state()
    if state.get("owned") is not True or state.get("state") != "running":
        return False
    # Require the exact configured model; a different or external model at
    # the memory port is never an acceptable router backend.
    return supervisor.model_ready()


def _wait_for_model(timeout=COLD_START_TIMEOUT):
    if not ctl.on_demand_enabled():
        raise RouterUnavailable("On-demand 4B is not enabled")
    if not supervisor.valid_settings():
        raise RouterUnavailable("Dedicated 4B must be enabled before shared routing")
    if ctl.active_media_kind():
        raise RouterUnavailable("Image/video has priority over routing")
    ctl.request_router_demand(seconds=max(150, timeout + 30))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _ready():
            return
        if ctl.active_media_kind():
            raise RouterUnavailable("Image/video has priority over routing")
        time.sleep(0.25)
    raise RouterUnavailable("Supervised shared 4B did not become ready")


def complete(payload, *, timeout=180):
    """Perform only an allowlisted non-streaming local router completion."""
    if not isinstance(payload, dict) or payload.get("stream") is True:
        raise ValueError("Streaming router requests are not supported")
    if payload.get("model") != str(supervisor.MODEL):
        raise ValueError("Router model must equal the supervised local 4B")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_REQUEST:
        raise ValueError("Router input exceeds the local limit")
    global _ACTIVE
    # Inference remains protected for its entire duration. No overlapping
    # media worker can load its large model while router inference is active.
    with rc.runtime_lease(workload="router", timeout=30):
        _wait_for_model()
        with ctl.inference_lease():
            with _ACTIVE_LOCK:
                _ACTIVE += 1
            try:
                request = urllib.request.Request(
                    UPSTREAM + "/v1/chat/completions",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with _OPENER.open(request, timeout=timeout) as response:
                    result = response.read(MAX_RESPONSE + 1)
                if len(result) > MAX_RESPONSE:
                    raise RouterUnavailable("4B response exceeds limit")
                output = json.loads(result)
                if not isinstance(output, dict):
                    raise RouterUnavailable("4B returned invalid response")
                return output
            except (OSError, urllib.error.HTTPError, ValueError) as exc:
                raise RouterUnavailable("Shared 4B inference unavailable") from exc
            finally:
                with _ACTIVE_LOCK:
                    _ACTIVE -= 1


class Handler(BaseHTTPRequestHandler):
    server_version = "NobbyRouterGateway/1"
    sys_version = ""

    def log_message(self, _format, *_args):
        # Do not log URLs, request text, or headers.
        return

    def _respond(self, status, obj):
        raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, health())
        elif self.path == "/v1/models":
            self._respond(200, {
                "object": "list",
                "data": [{"id": str(supervisor.MODEL), "object": "model"}],
            })
        else:
            self._respond(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/unload":
            # This gateway holds no model weights. Media preempts the shared
            # 8011 model through the existing dedicated-memory supervisor.
            self._respond(200, {"ok": True, "loaded": False})
            return
        if self.path != "/v1/chat/completions":
            self._respond(404, {"error": "Not found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except (ValueError, TypeError):
            size = 0
        if not 0 < size <= MAX_REQUEST:
            self._respond(413, {"error": "Invalid request size"})
            return
        try:
            payload = json.loads(self.rfile.read(size))
            self._respond(200, complete(payload))
        except (ValueError, TypeError):
            self._respond(422, {"error": "Invalid router request"})
        except (RouterUnavailable, TimeoutError, rc.CoordinationCancelled):
            self._respond(503, {"error": "Router temporarily unavailable"})
        except Exception:
            # Never expose model/backend exception details or private input.
            self._respond(503, {"error": "Router temporarily unavailable"})


def main():
    # Binding only to loopback is mandatory, even with a custom startup.
    with ThreadingHTTPServer((HOST, PORT), Handler) as server:
        server.daemon_threads = True
        server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
