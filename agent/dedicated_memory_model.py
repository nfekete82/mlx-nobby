"""Opt-in, independent loopback-only inference backend for memory extraction.

The existing single-model chat backend remains the default. Dedicated mode only
talks to an explicitly configured local OpenAI-compatible server on 127.0.0.1.
It does not launch/swap models or change the durable analysis queue.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from agent import personal_memory as pm

SETTING = "memory_extraction_backend"
DEFAULT_PORT = 8011
MAX_RESPONSE_BYTES = 2_000_000
MAX_TIMEOUT_SECONDS = 180
_RESERVED = frozenset({8000, 8010, 8020, 8030, 8040, 8050, 8060,
                       8070, 8081, 8090, 8095, 8096})
_DEFAULT = {"mode": "chat", "port": DEFAULT_PORT, "model": ""}


class MemoryModelError(RuntimeError):
    """A memory inference failure; never contains raw chat content."""


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Explicitly disable environment proxies; never follow redirects to remote hosts.
_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), _NoRedirects(),
)


def _checked(settings):
    if not isinstance(settings, dict):
        raise ValueError("Invalid memory model settings")
    if set(settings) - {"mode", "port", "model"}:
        raise ValueError("Unknown memory model setting")
    values = {**_DEFAULT, **settings}
    if values["mode"] not in ("chat", "dedicated"):
        raise ValueError("mode must be chat or dedicated")
    port = values["port"]
    if type(port) is not int or not 1024 <= port <= 65535 or port in _RESERVED:
        raise ValueError("Invalid or reserved local memory model port")
    model = values["model"]
    if not isinstance(model, str) or len(model) > 240 or (
        model and (not model.strip() or re.search(r"[\x00-\x1f\x7f]", model))
    ):
        raise ValueError("Invalid local model identifier")
    if values["mode"] == "dedicated" and not model:
        raise ValueError("dedicated mode requires a model identifier")
    return values


def settings():
    """Read the existing backup-covered private SQLite settings, without writes."""
    if not pm.DB_PATH.is_file():
        return dict(_DEFAULT)
    with pm.LOCK, pm._connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (SETTING,)
        ).fetchone()
    if row is None:
        return dict(_DEFAULT)
    try:
        return _checked(json.loads(row["value"]))
    except (ValueError, TypeError) as exc:
        raise MemoryModelError("Invalid stored memory model configuration") from exc


def _request(port, path, *, payload=None, timeout=5):
    url = f"http://127.0.0.1:{port}{path}"
    request = urllib.request.Request(
        url,
        data=(json.dumps(payload, ensure_ascii=False).encode("utf-8")
              if payload is not None else None),
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise MemoryModelError("Local memory model returned non-200 status")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
            ConnectionError, OSError) as exc:
        # Do not return the response body: an error page may contain prompt text.
        raise MemoryModelError("Local memory model unavailable or rejected request") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise MemoryModelError("Local memory model response too large")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise MemoryModelError("Invalid local memory model JSON response") from exc


def probe(port, model):
    """Verify that the exact model is served before opting into dedicated mode."""
    result = _request(port, "/v1/models", timeout=4)
    if not isinstance(result, dict) or not isinstance(result.get("data"), list):
        raise MemoryModelError("Local memory model did not return a model catalog")
    ids = {item.get("id") for item in result["data"]
           if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if model not in ids:
        raise MemoryModelError("Configured model is not served by the local memory endpoint")
    return True


def configure(payload):
    """Opt-in switch: verify local server first, then commit settings atomically."""
    if not isinstance(payload, dict):
        raise ValueError("Expected a settings object")
    desired = _checked({**settings(), **payload})
    if desired["mode"] == "dedicated":
        probe(desired["port"], desired["model"])
    with pm.LOCK, pm._connect() as conn:
        pm._schema(conn)
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (SETTING, json.dumps(desired, sort_keys=True)),
        )
    return desired


def complete(messages):
    """Run one structured extraction on the selected fixed local model."""
    config = settings()
    if config["mode"] != "dedicated":
        raise MemoryModelError("Dedicated memory model is not enabled")
    if not isinstance(messages, list) or not all(
        isinstance(m, dict) and m.get("role") in ("system", "user", "assistant")
        and isinstance(m.get("content"), str) for m in messages
    ):
        raise ValueError("Invalid memory extraction messages")
    result = _request(
        config["port"], "/v1/chat/completions",
        payload={
            "model": config["model"],
            "messages": messages,
            "temperature": 0,
            "max_tokens": 3000,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=MAX_TIMEOUT_SECONDS,
    )
    try:
        choice = result["choices"][0]
        message = choice["message"]
        output = message.get("content") or message.get("reasoning")
        finish_reason = choice.get("finish_reason")
        if not isinstance(output, str) or not output.strip():
            raise ValueError("Missing model content")
        if finish_reason == "length":
            raise ValueError("Truncated model output")
    except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
        raise MemoryModelError("Invalid or truncated local memory model response") from exc
    return output.strip()



def extract(messages, fallback):
    """Select exactly one inference backend; never silently switch on failure."""
    if settings()["mode"] == "dedicated":
        return complete(messages)
    return fallback(messages)


def status():
    """No network calls for normal UI polling."""
    return settings()
