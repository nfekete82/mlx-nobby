"""Automation API and native scheduler for MLX nobby."""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from fastapi import FastAPI, HTTPException, Query

from agent import automations


logger = logging.getLogger(__name__)
LOCAL_AGENT_URL = "http://127.0.0.1:8010"
SCHEDULER_INTERVAL_SECONDS = 15
_SCHEDULER_LOCK = threading.Lock()
_SCHEDULER_STARTED = False


def _json_request(method: str, path: str, payload=None, *, timeout=900):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        LOCAL_AGENT_URL + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("detail", body)
        except Exception:
            detail = body
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Local agent request failed: {exc}") from exc


def _model_scout_result(data: dict) -> dict:
    candidates = []
    for item in (data.get("candidates") or [])[:12]:
        if not isinstance(item, dict):
            continue
        candidates.append({
            "id": item.get("id"),
            "role": item.get("role"),
            "discovery_score": item.get("discovery_score"),
            "memory_fit": item.get("memory_fit"),
            "estimated_memory_gb": item.get("estimated_memory_gb"),
            "last_modified": item.get("last_modified"),
            "downloads": item.get("downloads"),
            "license": item.get("license"),
            "tuning_markers": item.get("tuning_markers") or [],
            "installed": bool(item.get("installed")),
            "benchmark_ready": bool(item.get("benchmark_ready")),
        })
    return {
        "kind": "model_scout",
        "count": len(data.get("candidates") or []),
        "source": data.get("source"),
        "system": data.get("system"),
        "candidates": candidates,
    }


def _execute_automation(run_id: str, automation: dict) -> None:
    try:
        automations.start_run(run_id)
        if automation.get("kind") == "model_scout":
            query = urllib.parse.urlencode({"limit": 36, "role": "all"})
            data = _json_request("GET", f"/api/model-scout/discover?{query}", timeout=45)
            automations.finish_run(
                run_id,
                status="completed",
                result=_model_scout_result(data),
            )
            return

        agent_run_id = "auto-" + uuid.uuid4().hex[:18]
        payload = {
            "goal": automation.get("prompt") or "",
            "mode": automation.get("mode") or "diagnostic",
            "run_id": agent_run_id,
            "trace_id": "automation-" + run_id,
            "workspace_id": automation.get("workspace_id"),
            "workspace_bound": bool(automation.get("workspace_id")),
            "conversation_context": [],
        }
        data = _json_request("POST", "/api/agent/run", payload, timeout=900)
        terminal = "needs_approval" if data.get("pending_action") else "completed"
        if data.get("status") in {"failed", "cancelled"}:
            terminal = data["status"]
        automations.finish_run(run_id, status=terminal, result=data)
    except Exception as exc:
        logger.exception("Automation run failed (run_id=%s)", run_id)
        try:
            automations.finish_run(run_id, status="failed", error=str(exc))
        except Exception:
            logger.exception("Could not persist failed automation run (run_id=%s)", run_id)


def _start_worker(run_id: str, automation: dict) -> None:
    thread = threading.Thread(
        target=_execute_automation,
        args=(run_id, automation),
        name=f"mlx-automation-{run_id[:8]}",
        daemon=True,
    )
    thread.start()


def _scheduler_loop() -> None:
    # Give the agent routes a moment to finish booting before the first claim.
    time.sleep(3)
    while True:
        try:
            for claimed in automations.claim_due(limit=4):
                _start_worker(claimed["run_id"], claimed["automation"])
        except Exception:
            logger.exception("Automation scheduler tick failed")
        time.sleep(SCHEDULER_INTERVAL_SECONDS)


def start_scheduler() -> None:
    global _SCHEDULER_STARTED
    with _SCHEDULER_LOCK:
        if _SCHEDULER_STARTED:
            return
        _SCHEDULER_STARTED = True
        thread = threading.Thread(
            target=_scheduler_loop,
            name="mlx-automation-scheduler",
            daemon=True,
        )
        thread.start()


def _automation_or_404(automation_id: str) -> dict:
    item = automations.get_automation(automation_id)
    if item is None:
        raise HTTPException(404, "Automation nicht gefunden")
    return item


def install_routes(app: FastAPI) -> None:
    paths = {getattr(route, "path", None) for route in app.router.routes}

    if "/api/automations" not in paths:
        @app.get("/api/automations")
        def automation_list():
            return {"automations": automations.list_automations()}

        @app.post("/api/automations", status_code=201)
        def automation_create(request: dict):
            try:
                return automations.create_automation(request)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc

    if "/api/automations/runs" not in paths:
        @app.get("/api/automations/runs")
        def automation_runs(
            automation_id: str | None = None,
            limit: int = Query(default=50, ge=1, le=200),
        ):
            if automation_id:
                _automation_or_404(automation_id)
            return {
                "runs": automations.list_runs(
                    automation_id=automation_id,
                    limit=limit,
                )
            }

    if "/api/automations/{automation_id}" not in paths:
        @app.get("/api/automations/{automation_id}")
        def automation_get(automation_id: str):
            return _automation_or_404(automation_id)

        @app.put("/api/automations/{automation_id}")
        def automation_update(automation_id: str, request: dict):
            try:
                return automations.update_automation(automation_id, request)
            except KeyError as exc:
                raise HTTPException(404, "Automation nicht gefunden") from exc
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc

        @app.delete("/api/automations/{automation_id}")
        def automation_delete(automation_id: str):
            if not automations.delete_automation(automation_id):
                raise HTTPException(404, "Automation nicht gefunden")
            return {"ok": True}

    if "/api/automations/{automation_id}/run" not in paths:
        @app.post("/api/automations/{automation_id}/run", status_code=202)
        def automation_run_now(automation_id: str):
            automation = _automation_or_404(automation_id)
            try:
                run = automations.create_run(automation_id, trigger="manual")
            except RuntimeError as exc:
                raise HTTPException(409, "Automation läuft bereits") from exc
            _start_worker(run["id"], automation)
            return run

    if "/api/automations/runs/{run_id}" not in paths:
        @app.get("/api/automations/runs/{run_id}")
        def automation_run_get(run_id: str):
            run = automations.get_run(run_id)
            if run is None:
                raise HTTPException(404, "Automation-Lauf nicht gefunden")
            return run

    start_scheduler()


__all__ = ["install_routes", "start_scheduler"]
