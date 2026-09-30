"""Image Pipeline V2 layer: intent routing, SDXL prewarm and safe telemetry.

This module wraps the stable native image service instead of duplicating it.
Launchd points uvicorn here so the existing API/jobs remain unchanged.
"""

from __future__ import annotations

import copy
import json
import os
import secrets
import selectors
import threading
import time
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

import image_pipeline_v2 as pipeline_v2
import image_providers
import image_registry as registry
import image_service as core
import runtime_coordinator


app = core.app

_route_local = threading.local()
_state_lock = threading.RLock()
_pipeline_state = {
    "version": 2,
    "last_route": None,
    "last_generation": None,
    "prewarm": {
        "status": "idle",
        "model": None,
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "error": None,
    },
}
_prewarm_thread = None


class PrewarmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(default="", max_length=2000)
    model: str = "auto"


def _set_state(key, value):
    with _state_lock:
        _pipeline_state[key] = copy.deepcopy(value)


def _update_prewarm(**changes):
    with _state_lock:
        current = dict(_pipeline_state.get("prewarm") or {})
        current.update(changes)
        _pipeline_state["prewarm"] = current


def _safe_route(plan, selected=None, explicit=False):
    return {
        "version": 2,
        "intent": "explicit" if explicit else plan.get("intent", "generic"),
        "reason": "explicit-model" if explicit else plan.get("reason", "default"),
        "signals": {} if explicit else dict(plan.get("signals") or {}),
        "candidates": [] if explicit else list(plan.get("candidates") or []),
        "selected_model": selected,
    }


def _candidate(data, model_id):
    model = next(
        (item for item in data["models"] if item["id"] == model_id),
        None,
    )
    if (
        not model
        or not model.get("enabled")
        or "text_to_image" not in model.get("capabilities", [])
    ):
        return None
    ready, _ = core.availability(model)
    return model if ready else None


def _route_generation_model(model_id, prompt):
    if model_id != "auto":
        model = core.registry_call(registry.get_model, model_id)
        route = _safe_route({}, selected=model["id"], explicit=True)
        _route_local.last = route
        _set_state("last_route", route)
        return model

    data = core.registry_call(registry.load_registry)
    plan = pipeline_v2.route_plan(prompt, data.get("default_model"))

    selected = None
    for candidate_id in plan["candidates"]:
        selected = _candidate(data, candidate_id)
        if selected:
            break

    if selected is None:
        for model in data["models"]:
            selected = _candidate(data, model["id"])
            if selected:
                break

    if selected is None:
        selected = core.registry_call(registry.get_model)

    route = _safe_route(plan, selected=selected["id"])
    _route_local.last = route
    _set_state("last_route", route)
    return selected


_original_generate_result = core._generate_result


def _observed_generate_result(
    request,
    *,
    provider_options=None,
    prepared_callback=None,
    saving_callback=None,
):
    started = time.monotonic()
    prepared_at = None
    first_progress_at = None
    provider_finished_at = None
    selected_model = None
    warm_before = image_providers.sdxl_worker_running()

    options = dict(provider_options or {})
    original_progress = options.get("progress_callback")

    def observed_progress(event):
        nonlocal first_progress_at
        if first_progress_at is None:
            first_progress_at = time.monotonic()
        if original_progress is not None:
            original_progress(event)

    options["progress_callback"] = observed_progress

    def observed_prepared(model, params, path):
        nonlocal prepared_at, selected_model
        prepared_at = time.monotonic()
        selected_model = model.get("id")
        if prepared_callback is not None:
            prepared_callback(model, params, path)

    def observed_saving():
        nonlocal provider_finished_at
        provider_finished_at = time.monotonic()
        if saving_callback is not None:
            saving_callback()

    _route_local.last = None
    try:
        result = _original_generate_result(
            request,
            provider_options=options,
            prepared_callback=observed_prepared,
            saving_callback=observed_saving,
        )
    except Exception:
        route = copy.deepcopy(getattr(_route_local, "last", None))
        finished = time.monotonic()
        _set_state("last_generation", {
            "status": "failed",
            "model": selected_model,
            "route": route,
            "timings_ms": {
                "total": round((finished - started) * 1000, 1),
            },
        })
        raise

    finished = time.monotonic()
    route = copy.deepcopy(getattr(_route_local, "last", None))
    timings = {
        "total": round((finished - started) * 1000, 1),
        "prepare": (
            round((prepared_at - started) * 1000, 1)
            if prepared_at is not None else None
        ),
        "first_progress": (
            round((first_progress_at - started) * 1000, 1)
            if first_progress_at is not None else None
        ),
        "provider": (
            round((provider_finished_at - prepared_at) * 1000, 1)
            if prepared_at is not None and provider_finished_at is not None
            else None
        ),
        "save_finalize": (
            round((finished - provider_finished_at) * 1000, 1)
            if provider_finished_at is not None else None
        ),
    }
    trace = {
        "version": 2,
        "route": route,
        "timings_ms": timings,
        "runtime": {
            "sdxl_warm_before": warm_before,
            "sdxl_warm_after": image_providers.sdxl_worker_running(),
        },
    }
    result["pipeline_trace"] = trace
    _set_state("last_generation", {
        "status": "completed",
        "model": result.get("model"),
        **trace,
    })
    return result


def _prewarm_sdxl(model):
    checkpoint, config = image_providers.sdxl_files(model)
    manager = image_providers._sdxl_worker_manager
    environment = os.environ.copy()
    environment.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        TOKENIZERS_PARALLELISM="false",
    )

    with manager._lock:
        manager._cancel_idle_timer_locked()
        process = manager._start_locked(environment)
        request_id = secrets.token_hex(16)
        request = {
            "request_id": request_id,
            "operation": "prewarm",
            "checkpoint": str(checkpoint),
            "config": str(config),
            "params": {"scheduler": "dpmpp-2m-karras"},
            "output": "",
        }
        succeeded = False
        try:
            process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
            process.stdin.flush()
            deadline = time.monotonic() + 180
            buffer = b""
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("SDXL prewarm timed out")
                    if process.poll() is not None:
                        raise RuntimeError(manager._failure_message_locked(process))
                    events = selector.select(0.25)
                    if not events:
                        continue
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        raise RuntimeError(manager._failure_message_locked(process))
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        try:
                            event = json.loads(line)
                        except (TypeError, ValueError):
                            continue
                        if event.get("request_id") != request_id:
                            continue
                        if event.get("type") == "error":
                            raise RuntimeError(
                                "SDXL prewarm failed: " +
                                str(event.get("error_type") or "unknown error")
                            )
                        if event.get("type") == "complete":
                            succeeded = True
                            break
                    if succeeded:
                        break
        finally:
            if succeeded:
                manager._schedule_idle_shutdown_locked()
            else:
                manager._stop_locked()


def _prewarm_worker(model, route):
    started_wall = time.time()
    started = time.monotonic()
    _update_prewarm(
        status="running",
        model=model["id"],
        route=route,
        started_at=started_wall,
        finished_at=None,
        duration_ms=None,
        error=None,
    )
    try:
        before = runtime_coordinator.memory_budget_snapshot()
        with runtime_coordinator.image_runtime(None) as preflight:
            _prewarm_sdxl(model)
        after = runtime_coordinator.memory_budget_snapshot()
        _update_prewarm(
            status="ready",
            finished_at=time.time(),
            duration_ms=round((time.monotonic() - started) * 1000, 1),
            memory_before=before,
            memory_after=after,
            preflight=preflight,
            error=None,
        )
    except Exception as exc:
        _update_prewarm(
            status="failed",
            finished_at=time.time(),
            duration_ms=round((time.monotonic() - started) * 1000, 1),
            error=type(exc).__name__,
        )


@app.post("/prewarm")
def prewarm(request: PrewarmRequest):
    global _prewarm_thread

    model = _route_generation_model(request.model, request.prompt)
    route = copy.deepcopy(getattr(_route_local, "last", None))

    if model.get("provider") != "sdxl":
        return {
            "ok": True,
            "started": False,
            "warm": False,
            "model": model["id"],
            "route": route,
            "reason": "provider-does-not-use-persistent-worker",
        }

    if image_providers.sdxl_worker_running():
        _update_prewarm(
            status="ready",
            model=model["id"],
            route=route,
            error=None,
        )
        return {
            "ok": True,
            "started": False,
            "warm": True,
            "model": model["id"],
            "route": route,
        }

    with _state_lock:
        if _prewarm_thread is not None and _prewarm_thread.is_alive():
            return {
                "ok": True,
                "started": False,
                "warm": False,
                "model": model["id"],
                "route": route,
                "reason": "prewarm-already-running",
            }
        _prewarm_thread = threading.Thread(
            target=_prewarm_worker,
            args=(model, route),
            name="mlx-image-prewarm",
            daemon=True,
        )
        _prewarm_thread.start()

    return {
        "ok": True,
        "started": True,
        "warm": False,
        "model": model["id"],
        "route": route,
    }


@app.get("/pipeline")
def pipeline_state():
    with _state_lock:
        state = copy.deepcopy(_pipeline_state)
    state["sdxl_worker_loaded"] = image_providers.sdxl_worker_running()
    state["runtime"] = runtime_coordinator.runtime_state_snapshot()
    return state


# Patch only the extension points used by existing synchronous and queued paths.
core._generation_model = _route_generation_model
core._generate_result = _observed_generate_result
