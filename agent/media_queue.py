"""Persistent FIFO queue for heavy image and video jobs.

The Agent owns the queue while the native image/video services continue to own
actual generation. This keeps existing service APIs intact, avoids 409 races,
and gives the UI one durable place to observe media work.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.request
import uuid

from fastapi import HTTPException

from agent import batch_state
import runtime_coordinator


QUEUE_DIRECTORY = Path.home() / ".config/mlx-web/media-queue"
QUEUE_FILE = QUEUE_DIRECTORY / "jobs.json"
SHORTS_FILE = Path.home() / ".config/mlx-web/shorts/jobs.json"
IMAGE_URL = os.environ.get(
    "IMAGE_SERVICE_URL", "http://127.0.0.1:8030"
).rstrip("/")
VIDEO_URL = os.environ.get(
    "VIDEO_SERVICE_URL", "http://127.0.0.1:8060"
).rstrip("/")
JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{24}$")
KINDS = frozenset({"image", "video"})
TERMINAL = frozenset({"completed", "failed", "cancelled"})
MAX_RETAINED_JOBS = 200
POLL_INTERVAL = 0.75
SERVICE_RETRY_BASE_SECONDS = 1.5
SERVICE_RETRY_MAX_SECONDS = 30.0

_jobs_lock = threading.RLock()
_worker_lock = threading.Lock()
_wake = threading.Event()
_jobs = {}
_loaded = False
_worker_thread = None


class ServiceError(RuntimeError):
    def __init__(self, status_code, detail):
        super().__init__(str(detail))
        self.status_code = int(status_code)
        self.detail = detail


def _service_url(kind):
    if kind == "image":
        return IMAGE_URL
    if kind == "video":
        return VIDEO_URL
    raise ValueError("unsupported media queue kind")


def _service_request(kind, method, path, payload=None, timeout=20):
    request = urllib.request.Request(
        _service_url(kind) + path,
        method=method,
        data=(
            json.dumps(payload).encode("utf-8")
            if payload is not None
            else None
        ),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            detail = json.loads(raw.decode("utf-8")).get(
                "detail", "Media-Service-Fehler"
            )
        except (UnicodeDecodeError, ValueError, AttributeError):
            detail = "Media-Service-Fehler"
        raise ServiceError(exc.code, detail) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ServiceError(
            503,
            str(getattr(exc, "reason", exc)) or "Media-Service nicht erreichbar",
        ) from exc


def _ensure_loaded_locked():
    global _loaded
    if _loaded:
        return

    stored = batch_state.load_jobs(QUEUE_FILE)
    now = time.time()
    for job_id, raw in stored.items():
        if not isinstance(raw, dict):
            continue
        if not JOB_ID_PATTERN.fullmatch(str(job_id)):
            continue
        kind = raw.get("kind")
        if kind not in KINDS:
            continue
        job = dict(raw)
        job["id"] = str(job_id)
        if job.get("status") == "dispatching" and not job.get("native_job_id"):
            job.update(status="queued", phase="recovered")
        if job.get("status") not in TERMINAL and job.get("cancel_requested"):
            job.update(
                status="cancelled",
                phase="cancelled",
                finished_at=job.get("finished_at") or now,
            )
        _jobs[job_id] = job
    _loaded = True


def _persist_locked():
    batch_state.save_jobs(QUEUE_DIRECTORY, QUEUE_FILE, _jobs)


def _prune_locked():
    if len(_jobs) < MAX_RETAINED_JOBS:
        return
    terminal = [
        job for job in _jobs.values()
        if job.get("status") in TERMINAL
    ]
    terminal.sort(key=lambda item: float(item.get("finished_at") or 0))
    while len(_jobs) >= MAX_RETAINED_JOBS and terminal:
        _jobs.pop(terminal.pop(0)["id"], None)


def _public(job):
    value = {
        key: deepcopy(item)
        for key, item in job.items()
        if key != "request" and not key.startswith("_")
    }

    if (value.get("result") or {}).get("semantic_operation") == "reference_generate":
        value["result"].pop("source_path", None)

    # ``dispatching`` is an internal queue hand-off state between the Agent
    # and the native media service. Older clients do not know that state and
    # can mistake it for a terminal result, which stops their job poller and
    # leaves a chat card frozen forever. Keep the internal state for recovery
    # and persistence, but expose it as the normal active ``queued`` state.
    if value.get("status") == "dispatching":
        value["status"] = "queued"
        value["phase"] = "queued"

    value["cancellable"] = value.get("status") not in TERMINAL
    return value


def _title(kind, payload):
    request_payload = payload.get("payload") if isinstance(payload, dict) else None
    request_payload = request_payload if isinstance(request_payload, dict) else {}
    prompt = str(request_payload.get("prompt") or "").strip()
    if prompt:
        return prompt[:160]
    operation = str(payload.get("operation") or "") if isinstance(payload, dict) else ""
    if kind == "image" and operation == "upscale":
        return "Bild hochskalieren"
    if kind == "image":
        return "Bild erzeugen"
    return "Video erzeugen"


def _validated_id(value):
    value = str(value or "")
    if not JOB_ID_PATTERN.fullmatch(value):
        raise HTTPException(422, "Ungültige Job-ID")
    return value


def _validated_kind(kind):
    value = str(kind or "")
    if value not in KINDS:
        raise HTTPException(422, "Ungültiger Media-Job-Typ")
    return value


def _update(job_id, **changes):
    with _jobs_lock:
        _ensure_loaded_locked()
        job = _jobs.get(job_id)
        if job is None:
            return None
        if job.get("status") in TERMINAL:
            requested = changes.get("status")
            if requested is not None and requested != job.get("status"):
                return _public(job)
        job.update(changes)
        _persist_locked()
        return _public(job)


def enqueue(kind, request_payload):
    kind = _validated_kind(kind)
    if not isinstance(request_payload, dict):
        raise HTTPException(422, "Media-Job benötigt ein JSON-Objekt")

    payload = request_payload.get("payload")
    if kind == "video" and isinstance(payload, dict) and payload.get("profile") == "uncensored":
        # Ask the service owning the adapter environment before persisting a
        # queue job or waking the heavy-runtime scheduler.
        try:
            _service_request("video", "POST", "/preflight", request_payload)
        except ServiceError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc

    job_id = uuid.uuid4().hex[:24]
    now = time.time()
    job = {
        "id": job_id,
        "kind": kind,
        "title": _title(kind, request_payload),
        "operation": str(request_payload.get("operation") or ""),
        "chat_id": request_payload.get("chat_id"),
        "run_id": request_payload.get("run_id") or job_id,
        "chat_revision": request_payload.get("chat_revision", 0),
        "status": "queued",
        "phase": "queued",
        "progress": 0.0,
        "current_step": None,
        "total_steps": None,
        "model": (
            request_payload.get("payload", {}).get("model")
            if isinstance(request_payload.get("payload"), dict)
            else None
        ),
        "native_job_id": None,
        "dispatch_attempts": 0,
        "_retry_after": None,
        "request": deepcopy(request_payload),
        "result": None,
        "error": None,
        "cancel_requested": False,
        "created_at": now,
        "started_at": None,
        "finished_at": None,
    }
    payload = request_payload.get('payload')
    if kind == 'image' and isinstance(payload, dict) and payload.get('semantic_operation') == 'reference_generate':
        job.update(semantic_operation='reference_generate', reference_mode=payload.get('reference_mode'), reference_relation=payload.get('reference_mode'), reference_used=True)

    with _jobs_lock:
        _ensure_loaded_locked()
        _prune_locked()
        _jobs[job_id] = job
        _persist_locked()
        result = _public(job)

    ensure_worker()
    _wake.set()
    return result


def has_job(kind, job_id):
    kind = _validated_kind(kind)
    job_id = _validated_id(job_id)
    with _jobs_lock:
        _ensure_loaded_locked()
        job = _jobs.get(job_id)
        return bool(job and job.get("kind") == kind)


def get_job(kind, job_id):
    kind = _validated_kind(kind)
    job_id = _validated_id(job_id)
    with _jobs_lock:
        _ensure_loaded_locked()
        job = _jobs.get(job_id)
        if not job or job.get("kind") != kind:
            return None
        return _public(job)


def _mirror_native(job_id, native):
    copied = {}
    for key in (
        "status", "phase", "progress", "current_step", "total_steps",
        "model", "result", "error", "started_at", "finished_at",
        "semantic_operation", "reference_mode", "reference_relation", "reference_used",
        "provider", "model_family", "error_code", "error_provider", "error_model", "error_detail_safe",
        "runtime_handoff", "performance_timings", "provider_timing",
    ):
        if key in native:
            copied[key] = native.get(key)
    if native.get("status") in TERMINAL and copied.get("finished_at") is None:
        copied["finished_at"] = time.time()
    return _update(job_id, **copied)


def _cancel_requested(job_id):
    with _jobs_lock:
        _ensure_loaded_locked()
        job = _jobs.get(job_id)
        return bool(job and job.get("cancel_requested"))


def _wait(seconds=POLL_INTERVAL):
    _wake.wait(timeout=seconds)
    _wake.clear()


def _service_retry_delay(attempts):
    """Bound outage retries without ever abandoning the durable queued job."""
    return min(
        SERVICE_RETRY_MAX_SECONDS,
        SERVICE_RETRY_BASE_SECONDS * 2 ** min(12, max(0, int(attempts) - 1)),
    )


def _dispatch_and_poll(job_id):
    while True:
        with _jobs_lock:
            _ensure_loaded_locked()
            job = deepcopy(_jobs.get(job_id))
        if job is None or job.get("status") in TERMINAL:
            return
        if job.get("cancel_requested"):
            if not job.get("native_job_id"):
                _update(
                    job_id,
                    status="cancelled",
                    phase="cancelled",
                    finished_at=time.time(),
                    error=None,
                )
                return

        kind = job["kind"]
        native_id = job.get("native_job_id")
        if not native_id:
            if job.get("cancel_requested"):
                continue
            _update(
                job_id,
                status="dispatching",
                phase="dispatching",
                dispatch_attempts=int(job.get("dispatch_attempts") or 0) + 1,
            )
            try:
                native = _service_request(
                    kind,
                    "POST",
                    "/jobs",
                    job["request"],
                    timeout=30,
                )
            except ServiceError as exc:
                if exc.status_code in {409, 503}:
                    # Yield to the scheduler so jobs of another healthy kind
                    # can run. Keep the earliest blocked job at the front of
                    # its own kind to preserve FIFO and retry after backoff.
                    _update(
                        job_id,
                        status="queued",
                        phase="waiting_for_service",
                        error=None,
                        _retry_after=time.time() + _service_retry_delay(
                            job.get("dispatch_attempts", 0) + 1
                        ),
                    )
                    return
                _update(
                    job_id,
                    status="failed",
                    phase="failed",
                    error=exc.detail,
                    finished_at=time.time(),
                )
                return

            native_id = str(native.get("id") or "")
            if not JOB_ID_PATTERN.fullmatch(native_id):
                _update(
                    job_id,
                    status="failed",
                    phase="failed",
                    error="Media-Service lieferte keine gültige Job-ID",
                    finished_at=time.time(),
                )
                return
            _update(
                job_id,
                native_job_id=native_id,
                service_dispatch_wait_ms=round(max(0.0, time.time() - float(job.get("created_at") or time.time())) * 1000, 1),
                status=str(native.get("status") or "queued"),
                phase=str(native.get("phase") or "queued"),
                started_at=native.get("started_at") or time.time(),
                error=None,
                _retry_after=None,
            )
            _mirror_native(job_id, native)
            continue

        if job.get("cancel_requested"):
            try:
                native = _service_request(
                    kind,
                    "POST",
                    f"/jobs/{native_id}/cancel",
                    {},
                    timeout=30,
                )
                _mirror_native(job_id, native)
            except ServiceError as exc:
                if exc.status_code == 404:
                    _update(
                        job_id,
                        status="cancelled",
                        phase="cancelled",
                        error=None,
                        finished_at=time.time(),
                    )
                    return
            _wait(0.2)
            continue

        try:
            native = _service_request(
                kind,
                "GET",
                f"/jobs/{native_id}",
                timeout=15,
            )
        except ServiceError as exc:
            if exc.status_code == 503:
                _wait()
                continue
            _update(
                job_id,
                status="failed",
                phase="failed",
                error=(
                    "Media-Service verlor den laufenden Job"
                    if exc.status_code == 404
                    else exc.detail
                ),
                finished_at=time.time(),
            )
            return

        mirrored = _mirror_native(job_id, native) or {}
        if mirrored.get("status") in TERMINAL:
            return
        _wait()


def _next_job_id():
    """Select the oldest runnable job without overtaking jobs of its kind.

    A dispatched native job is always polled before dispatching another heavy
    job; the coordinator and media worker remain deliberately single-flight.
    """
    with _jobs_lock:
        _ensure_loaded_locked()
        candidates = sorted(
            (job for job in _jobs.values() if job.get("status") not in TERMINAL),
            key=lambda item: (float(item.get("created_at") or 0), item["id"]),
        )
        # In-flight native jobs must not be left running while new jobs
        # dispatch, including after agent restart.
        for job in candidates:
            if job.get("native_job_id"):
                return job["id"]

        now = time.time()
        seen_kinds = set()
        for job in candidates:
            kind = job["kind"]
            if kind in seen_kinds:
                continue
            seen_kinds.add(kind)
            retry_after = float(job.get("_retry_after") or 0)
            if job.get("cancel_requested") or retry_after <= now:
                return job["id"]
        return None


def _scheduler_wait_seconds():
    """Sleep until the nearest retry or a new job, at most five seconds."""
    with _jobs_lock:
        _ensure_loaded_locked()
        pending = [
            float(job.get("_retry_after") or 0)
            for job in _jobs.values()
            if job.get("status") not in TERMINAL
            and not job.get("native_job_id")
            and job.get("_retry_after")
        ]
    if not pending:
        return 5.0
    return max(0.1, min(5.0, min(pending) - time.time()))


def _worker():
    while True:
        job_id = _next_job_id()
        if job_id is None:
            _wait(_scheduler_wait_seconds())
            continue
        try:
            _dispatch_and_poll(job_id)
        except Exception as exc:
            _update(
                job_id,
                status="failed",
                phase="failed",
                error=str(exc)[-4000:],
                finished_at=time.time(),
            )


def ensure_worker():
    global _worker_thread
    with _jobs_lock:
        _ensure_loaded_locked()
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return _worker_thread
        thread = threading.Thread(
            target=_worker,
            daemon=True,
            name="mlx-unified-media-queue",
        )
        _worker_thread = thread
        thread.start()
        return thread


def cancel(kind, job_id):
    kind = _validated_kind(kind)
    job_id = _validated_id(job_id)
    with _jobs_lock:
        _ensure_loaded_locked()
        job = _jobs.get(job_id)
        if not job or job.get("kind") != kind:
            return None
        if job.get("status") in TERMINAL:
            raise HTTPException(409, "Job kann nicht mehr abgebrochen werden")
        job["cancel_requested"] = True
        if not job.get("native_job_id"):
            job.update(
                status="cancelled",
                phase="cancelled",
                error=None,
                finished_at=time.time(),
            )
        _persist_locked()
        result = _public(job)
    _wake.set()
    return result


def cancel_chat(kind, chat_id, chat_revision=None):
    kind = _validated_kind(kind)
    with _jobs_lock:
        _ensure_loaded_locked()
        ids = [
            job["id"]
            for job in _jobs.values()
            if job.get("kind") == kind
            and job.get("status") not in TERMINAL
            and job.get("chat_id") == chat_id
            and (
                chat_revision is None
                or job.get("chat_revision") == chat_revision
            )
        ]
    cancelled = []
    for job_id in ids:
        value = cancel(kind, job_id)
        if value is not None:
            cancelled.append(value)
    return cancelled


def _short_jobs():
    jobs = batch_state.load_jobs(SHORTS_FILE)
    return [
        deepcopy(job)
        for job in jobs.values()
        if isinstance(job, dict)
        and JOB_ID_PATTERN.fullmatch(str(job.get("id") or ""))
    ]


def _queue_state(status, phase):
    status = str(status or "")
    phase = str(phase or "")
    if status in TERMINAL:
        return status
    if status in {"queued", "dispatching"} or phase in {
        "queued", "dispatching", "waiting_for_service", "waiting_for_resources",
    }:
        return "waiting"
    return "running"


def _short_progress(job, child):
    project = job.get("project") if isinstance(job.get("project"), dict) else {}
    scenes = project.get("scenes") if isinstance(project.get("scenes"), list) else []
    count = max(1, len(scenes))
    current = min(count, max(0, int(job.get("current_scene") or 0)))
    video_progress = current / count
    if child and current < count:
        try:
            child_progress = float(child.get("progress") or 0)
        except (TypeError, ValueError):
            child_progress = 0.0
        video_progress = min(1.0, (current + child_progress) / count)
    progress = video_progress * 0.8
    phase = str(job.get("phase") or "")
    if phase in {"video_completed", "tts"}:
        progress = max(progress, 0.82)
    if phase == "tts_completed":
        progress = max(progress, 0.9)
    if phase == "compose":
        progress = max(progress, 0.95)
    if job.get("status") == "completed":
        progress = 1.0
    return round(min(1.0, max(0.0, progress)), 4)


def _short_item(job, queue_by_id):
    child_id = str(job.get("active_video_job_id") or "")
    child = queue_by_id.get(child_id)
    raw_status = str(job.get("status") or "queued")
    raw_phase = str(job.get("phase") or raw_status)
    queue_state = _queue_state(raw_status, raw_phase)
    queue_created_at = float(job.get("created_at") or 0)
    if child and child.get("status") not in TERMINAL:
        queue_state = _queue_state(child.get("status"), child.get("phase"))
        queue_created_at = float(child.get("created_at") or queue_created_at)
        raw_phase = (
            "video_" + str(child.get("phase") or child.get("status") or "queued")
        )
    project = job.get("project") if isinstance(job.get("project"), dict) else {}
    return {
        "id": job.get("id"),
        "kind": "shorts",
        "title": str(project.get("title") or "Shorts Media Composer"),
        "operation": "shorts",
        "chat_id": job.get("chat_id"),
        "run_id": job.get("run_id"),
        "status": raw_status,
        "phase": raw_phase,
        "queue_status": queue_state,
        "progress": _short_progress(job, child),
        "current_scene": job.get("current_scene"),
        "scene_count": len(project.get("scenes") or []),
        "child_job_id": child_id or None,
        "created_at": job.get("created_at"),
        "queue_created_at": queue_created_at,
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "error": job.get("error"),
        "cancellable": raw_status not in TERMINAL,
    }


def snapshot(limit=40):
    ensure_worker()
    with _jobs_lock:
        _ensure_loaded_locked()
        media = [_public(job) for job in _jobs.values()]

    queue_by_id = {job["id"]: job for job in media}
    shorts = _short_jobs()
    child_ids = {
        str(job.get("active_video_job_id") or "")
        for job in shorts
        if job.get("active_video_job_id")
    }
    for short in shorts:
        for result in short.get("scene_results") or []:
            child_id = str(result.get("video_job_id") or "")
            if child_id:
                child_ids.add(child_id)

    items = []
    for job in media:
        if job["id"] in child_ids:
            continue
        item = deepcopy(job)
        item["queue_status"] = _queue_state(
            item.get("status"), item.get("phase")
        )
        item["queue_created_at"] = float(item.get("created_at") or 0)
        items.append(item)
    items.extend(_short_item(job, queue_by_id) for job in shorts)

    waiting = sorted(
        [item for item in items if item.get("queue_status") == "waiting"],
        key=lambda item: float(item.get("queue_created_at") or 0),
    )
    for position, item in enumerate(waiting, start=1):
        item["queue_position"] = position

    def sort_key(item):
        state = item.get("queue_status")
        rank = 0 if state == "running" else 1 if state == "waiting" else 2
        timestamp = float(
            item.get("queue_created_at")
            or item.get("created_at")
            or item.get("finished_at")
            or 0
        )
        return (rank, timestamp if rank < 2 else -timestamp)

    items.sort(key=sort_key)
    try:
        limit = max(1, min(100, int(limit)))
    except (TypeError, ValueError):
        limit = 40

    return {
        "jobs": items[:limit],
        "active_count": sum(
            item.get("queue_status") == "running" for item in items
        ),
        "waiting_count": sum(
            item.get("queue_status") == "waiting" for item in items
        ),
        "runtime": runtime_coordinator.runtime_state_snapshot(),
        "persistent": True,
    }


def cancel_public(kind, job_id):
    job_id = _validated_id(job_id)
    if kind == "shorts":
        from agent import shorts_jobs
        try:
            job = shorts_jobs.cancel_short_job(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Shorts-Job nicht gefunden") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"ok": True, "kind": "shorts", "job": job}

    kind = _validated_kind(kind)
    job = cancel(kind, job_id)
    if job is None:
        try:
            native = _service_request(
                kind,
                "POST",
                f"/jobs/{job_id}/cancel",
                {},
                timeout=30,
            )
        except ServiceError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        return {"ok": True, "kind": kind, "job": native}
    return {"ok": True, "kind": kind, "job": job}
