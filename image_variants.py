"""Sequential normal Generate jobs from a private, frozen source configuration."""
import copy
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from agent.batch_state import atomic_write_with

_RECORD_LOCK = threading.RLock()
_TERMINAL = {"completed", "failed", "cancelled"}


class VariantBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_job_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    count: int = Field(default=3, ge=2, le=6, strict=True)
    include_base: bool = True
    chat_id: str = Field(min_length=1)
    chat_revision: int = Field(ge=0, strict=True)
    variant_group_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")


def valid_image_file(job):
    try:
        result = job.get("result")
        if not isinstance(result, dict):
            return False
        path = Path(result.get("path") or "")
        return path.is_file() and path.stat().st_size > 0
    except (OSError, TypeError, ValueError):
        return False


def save_record(output, key, value):
    directory = output / ".variants"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    def write(path):
        with path.open("w", encoding="utf-8") as stream:
            os.chmod(path, 0o600)
            json.dump(value, stream, ensure_ascii=False)
    with _RECORD_LOCK:
        atomic_write_with(directory / (key + ".json"), write)


def load_record(output, key):
    if not re.fullmatch(r"(?:job|group)-[a-f0-9]{24}", key):
        return None
    try:
        value = json.loads((output / ".variants" / (key + ".json")).read_text())
        if not isinstance(value, dict):
            return None
        canonical = value.get("canonical")
        if not isinstance(canonical, dict) or not isinstance(canonical.get("model"), dict) or not isinstance(canonical.get("params"), dict):
            return None
        if not {"quality_profile", "requested_model", "requested_seed"} <= canonical.keys():
            return None
        if key.startswith("job-"):
            if not isinstance(value.get("job"), dict) or not isinstance(value.get("canonical"), dict):
                return None
        elif not isinstance(value.get("jobs"), list) or not isinstance(value.get("canonical"), dict) or not isinstance(value.get("request"), dict):
            return None
        else:
            if not {"id", "base_id", "base_job", "count", "include_base", "request_chat_id", "request_chat_revision"} <= value.keys():
                return None
            if not isinstance(value["base_job"], dict) or not all(isinstance(job, dict) and re.fullmatch(r"[a-f0-9]{24}", str(job.get("id", ""))) for job in value["jobs"]):
                return None
        return value
    except (OSError, ValueError):
        return None


def prune_records(service):
    """Keep latest terminal records, plus dependencies of retained/active groups.

    The existing job limit bounds groups and standalone sources separately.
    Each retained group pins at most six members and its source. Active groups
    and their dependencies are never removed; image files are never removed.
    """
    directory = service.OUTPUT / ".variants"
    protected = service._variant_active_keys()
    groups = sorted(directory.glob("group-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    pinned = set(protected)
    for index, path in enumerate(groups):
        if index >= service._MAX_RETAINED_JOBS and path.stem not in protected:
            path.unlink(missing_ok=True)
            continue
        record = load_record(service.OUTPUT, path.stem)
        if record:
            pinned.add("job-" + record["base_id"])
            pinned.update("job-" + job["id"] for job in record["jobs"])
    jobs = sorted(directory.glob("job-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for index, path in enumerate(jobs):
        if index >= service._MAX_RETAINED_JOBS and path.stem not in pinned:
            path.unlink(missing_ok=True)


def persist_record(service, key, value):
    with _RECORD_LOCK:
        save_record(service.OUTPUT, key, value)
        prune_records(service)


def install(service):
    groups = {}
    # Read a stable tuple without taking the jobs lock: writers already hold it
    # during start and otherwise run while the service-wide render lock is held.
    def active_keys():
        return {key for group in tuple(groups.values()) if group.get("running")
                for key in ["group-" + group["id"], "job-" + group["base_id"],
                            *("job-" + job["id"] for job in group["jobs"])]}
    service._variant_active_keys = active_keys

    def persist(group):
        with service._jobs_lock:
            record = copy.deepcopy({
                key: value for key, value in group.items()
                if key not in {"cancel", "running", "jobs"}
            } | {"jobs": [service._job_snapshot(job) for job in group["jobs"]]})
        persist_record(service, "group-" + group["id"], record)

    def reusable(job):
        return job.get("status") == "completed" and valid_image_file(job)

    def group_status(group):
        statuses = [job["status"] for job in group["jobs"]]
        if group.get("running"):
            return "running"
        if all(status == "completed" for status in statuses):
            return "completed"
        return "cancelled" if "cancelled" in statuses else "failed"

    def run(group):
        try:
            for job in group["jobs"]:
                if reusable(job):
                    continue
                if group["cancel"].is_set():
                    service._update_job(job["id"], status="cancelled", finished_at=time.time())
                    continue
                with service._jobs_lock:
                    service._active_job_id = job["id"]
                request = service.Generate.model_validate(group["request"])
                request.seed = job["seed"]
                service._run_image_job(job["id"], "generate", request,
                                       resolved=group["canonical"], release_lock=False)
                persist(group)
                if job["status"] != "completed":
                    for missing in group["jobs"]:
                        if missing["status"] == "queued":
                            service._update_job(missing["id"], status="cancelled" if group["cancel"].is_set() else "failed",
                                                error="Previous variant failed", finished_at=time.time())
                    break
        except Exception:
            for job in group["jobs"]:
                if job["status"] not in _TERMINAL:
                    service._update_job(job["id"], status="failed",
                                        error="Variant batch could not continue", finished_at=time.time())
        finally:
            with service._jobs_lock:
                service._active_job_id = None
                group["running"] = False
            try:
                persist(group)
            except (OSError, ValueError, TypeError):
                group["persistence_available"] = False
            finally:
                service._lock.release()

    def restore(group_id):
        group = groups.get(group_id)
        if group is None:
            group = load_record(service.OUTPUT, "group-" + group_id)
            if group:
                for job in group["jobs"]:
                    completed = load_record(service.OUTPUT, "job-" + job["id"])
                    if completed and completed["job"].get("variant_group_id") == group_id:
                        job.update(completed["job"])
                group["running"] = False
                groups[group_id] = group
        if group and not group.get("running"):
            for job in group["jobs"]:
                if job.get("status") not in _TERMINAL or (job.get("status") == "completed" and not valid_image_file(job)):
                    job.update(status="failed", phase="failed", result=None,
                               error="Variant image unavailable; retry required")
        return group

    def owned_group(group_id, chat_id, chat_revision):
        group = restore(group_id)
        if not group or group["request_chat_id"] != chat_id or group["request_chat_revision"] != chat_revision:
            raise HTTPException(404, "Variant group not found")
        return group

    def response(group):
        base = copy.deepcopy(group["base_job"])
        # Group presentation is a copy; never mutate source metadata.
        if group["include_base"]:
            base["result"].update(variant_group_id=group["id"], variant_index=1,
                                  variant_count=group["count"], source_generation_job_id=group["base_id"])
        return {"variant_group_id": group["id"], "variant_count": group["count"],
                "status": group_status(group), "persistence_available": group.get("persistence_available", True),
                "base_job": base, "jobs": [service._job_snapshot(job) for job in group["jobs"]]}

    @service.app.get("/variant-groups/{group_id}")
    def status(group_id: str, chat_id: str, chat_revision: int):
        with service._jobs_lock:
            return response(owned_group(group_id, chat_id, chat_revision))

    @service.app.post("/variant-groups/{group_id}/cancel")
    def cancel(group_id: str, chat_id: str, chat_revision: int):
        with service._jobs_lock:
            group = owned_group(group_id, chat_id, chat_revision)
            if group.get("running"):
                group["cancel"].set()
                active = service._active_job_id
            else:
                active = None
        if active:
            service.cancel_image_job(active)
        with service._jobs_lock:
            return response(group)

    @service.app.post("/jobs/variants", status_code=202)
    def create_variants(request: VariantBatch):
        with service._jobs_lock:
            base = service._jobs.get(request.base_job_id)
            if base is None:
                record = load_record(service.OUTPUT, "job-" + request.base_job_id)
                if record:
                    base = dict(record["job"], _canonical=record["canonical"])
            if not base or base.get("chat_id") != request.chat_id or base.get("chat_revision") != request.chat_revision:
                raise HTTPException(404, "Base image job not found for this chat revision")
            if base.get("operation") != "generate" or not reusable(base) or not base.get("_canonical") or base.get("variants_available") is False:
                raise HTTPException(409, "Variants require an available completed Generate job")
            group = None
            if request.variant_group_id:
                group = owned_group(request.variant_group_id, request.chat_id, request.chat_revision)
                if group["base_id"] != base["id"] or group["count"] != request.count or group["include_base"] != request.include_base:
                    raise HTTPException(404, "Variant group not found")
                if group.get("running"):
                    raise HTTPException(409, "Variant group is running")
                if all(reusable(job) for job in group["jobs"]):
                    return response(group)
            if not service._lock.acquire(blocking=False):
                raise HTTPException(409, "An image job is already running")
            try:
                cancel_event = threading.Event()
                if group is None:
                    canonical = copy.deepcopy(base["_canonical"])
                    payload = {key: value for key, value in canonical["params"].items() if key in service.Generate.model_fields}
                    payload.update(original_prompt=base["result"].get("original_prompt"),
                                   width=base["result"].get("requested_width", payload["width"]),
                                   height=base["result"].get("requested_height", payload["height"]), model=canonical["requested_model"])
                    group_id = secrets.token_hex(12)
                    base_seed = canonical["params"]["seed"]
                    if canonical.get("requested_seed") is not None:
                        seeds = [(base_seed + index) % (2**32) for index in range(1, request.count + 1)]
                    else:
                        seeds, used = [], {base_seed}
                        while len(seeds) < request.count:
                            seed = secrets.randbelow(2**32)
                            if seed not in used:
                                used.add(seed)
                                seeds.append(seed)
                    jobs = []
                    first_index = 2 if request.include_base else 1
                    for index in range(first_index, request.count + 1):
                        jobs.append({"id": secrets.token_hex(12), "operation": "generate", "chat_id": request.chat_id,
                            "chat_revision": request.chat_revision, "run_id": base["run_id"],
                            "status": "queued", "phase": "queued", "progress": 0.0,
                            "model": canonical["model"]["id"], "provider": canonical["model"]["provider"],
                            "model_family": canonical["model"]["model_family"], "current_step": None,
                            "total_steps": canonical["params"]["steps"], "seed": seeds[index-first_index],
                            "result": None, "error": None, "created_at": time.time(), "started_at": None, "finished_at": None,
                            "variant_group_id": group_id, "variant_index": index, "variant_count": request.count,
                            "source_generation_job_id": base["id"], "_cancel_event": cancel_event, "_process": None, "_output_path": None})
                    group = {"id": group_id, "base_id": base["id"], "count": request.count,
                             "include_base": request.include_base, "jobs": jobs, "canonical": canonical, "request": payload,
                             "base_job": service._job_snapshot(base), "request_chat_id": request.chat_id,
                             "request_chat_revision": request.chat_revision}
                    for old_id, old in list(groups.items()):
                        if len(groups) < service._MAX_RETAINED_JOBS:
                            break
                        if not old.get("running"):
                            groups.pop(old_id)
                    groups[group_id] = group
                group.update(cancel=cancel_event, running=True, persistence_available=True)
                thread = threading.Thread(target=run, args=(group,), name="image-variants-" + group["id"], daemon=True)
                service._prune_jobs_locked()
                # Protect the immutable source against eviction while the batch runs.
                service._jobs[base["id"]] = base
                for job in group["jobs"]:
                    service._jobs[job["id"]] = job
                    if not reusable(job):
                        job.update(status="queued", phase="queued", error=None, result=None,
                                   current_step=None, progress=0.0, finished_at=None, _cancel_event=cancel_event, _thread=thread)
                service._active_job_id = next(job["id"] for job in group["jobs"] if job["status"] != "completed")
                persist(group)
                thread.start()
            except Exception:
                if group:
                    group.update(running=False, persistence_available=False)
                    for job in group["jobs"]:
                        if job["status"] not in _TERMINAL:
                            job.update(status="failed", phase="failed", error="Variant batch could not start", finished_at=time.time())
                    try:
                        persist(group)
                    except (OSError, ValueError, TypeError):
                        pass
                service._active_job_id = None
                service._lock.release()
                raise HTTPException(503, "Variant batch could not start") from None
            return response(group)

    return create_variants
