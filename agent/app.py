from pathlib import Path
from functools import wraps
from typing import Literal
import hashlib
import json
import queue
import os
import sys
import subprocess
import shutil
import re
import threading
import time
import uuid
import urllib.error
import urllib.request
import zlib
from agent import knowledge
from agent import profile
from agent import code_workspaces
from agent import disk_usage
from agent import image_api
from agent import model_cleanup
from agent.batch_processing import (
    BATCH_LARGE_CHUNK_TOKENS,
    BATCH_LARGE_FILE_TOKENS,
    BATCH_MAX_OUTPUT_TOKENS,
    BATCH_SINGLE_CHUNK_TOKENS,
    JSON_FREETEXT_BATCH_MAX_ITEMS,
    JSON_FREETEXT_BATCH_MAX_TOKENS,
    assemble_batch_json,
    batch_checkpoint_plan_id,
    batch_max_output_tokens,
    build_json_freetext_batches,
    decode_batch_bytes,
    estimate_batch_tokens,
    is_metal_oom_error,
    recommended_batch_chunk_tokens,
    split_batch_content,
    split_batch_part_for_oom,
    split_chunk_hard,
    write_batch_text,
)
from agent import batch_state
from backend import observability

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from local_security import LocalRequestGuard
from agent.service_proxy import install_routes as install_service_routes


app = FastAPI(title="MLX macOS Agent")
app.add_middleware(LocalRequestGuard)

CONFIG = Path.home() / ".config/mlx-server/config"
MODELS = Path.home() / ".config/mlx-server/models"
MLX = Path.home() / "bin/mlx"
JOBS_FILE = Path.home() / ".config/mlx-server/jobs.json"
LOCAL_MODELS_ROOT = Path.home() / "Models"
IMAGE_SERVICE_URL = os.environ.get("IMAGE_SERVICE_URL", "http://127.0.0.1:8030").rstrip("/")
IMAGE_DIRECTORY = Path.home() / ".config/mlx-web/images"
IMAGE_ID_PATTERN = re.compile(r"^\d{10}-[0-9a-f]{12}$")
IMAGE_ARTIFACT_ID_PATTERN = re.compile(
    r"^image-(?P<image_id>\d{10}-[0-9a-f]{12})$"
)


class AddModelRequest(BaseModel):
    alias: str
    repo: str
    quantization: str | None = None


class HistoryCleanupRequest(BaseModel):
    scope: Literal['completed', 'failed', 'all']


def history_statuses(scope):
    scopes = {
        'completed': {'completed'},
        'failed': {'failed'},
        'all': {'completed', 'failed', 'cancelled', 'interrupted'},
    }
    if scope not in scopes:
        raise HTTPException(400, "Ungültiger Bereinigungsbereich")
    return scopes[scope]


class ChatSessionRequest(BaseModel):
    id: str
    title: str
    created: float
    updated: float
    messages: list[dict]
    settings: dict | None = None
    workspace: dict | None = None


CHAT_DIRECTORY = Path.home() / ".config/mlx-web/chats"
CHAT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


JOBS = {}
JOBS_LOCK = threading.Lock()
CHATS_LOCK = threading.Lock()
MODEL_RUNTIME_LOCK = threading.RLock()
install_service_routes(app, lambda: int(load_config().get("PORT", 8000)), MODEL_RUNTIME_LOCK)
JOB_PERSISTENCE_LOCK = threading.Lock()


def locked_model_change(function):
    """Serialize registry changes/download creation with destructive model actions."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not MODEL_RUNTIME_LOCK.acquire(blocking=False):
            raise HTTPException(409, "Eine andere Runtime-Aktion läuft bereits.")
        try:
            return function(*args, **kwargs)
        finally:
            MODEL_RUNTIME_LOCK.release()
    return wrapped

BATCH_WORKERS = {}
BATCH_WORKERS_LOCK = threading.Lock()

DOCUMENT_INDEX_JOBS = {}
DOCUMENT_INDEX_JOBS_LOCK = threading.Lock()


def validate_chat_id(chat_id):
    if not isinstance(chat_id, str) or not CHAT_ID_PATTERN.fullmatch(chat_id):
        raise HTTPException(
            status_code=400,
            detail="Ungültige Chat-ID",
        )

    return chat_id


def chat_path(chat_id):
    chat_id = validate_chat_id(chat_id)
    return CHAT_DIRECTORY / f"{chat_id}.json"


def without_streaming_fields(value):
    if isinstance(value, list):
        return [without_streaming_fields(item) for item in value]

    if isinstance(value, dict):
        return {
            key: without_streaming_fields(item)
            for key, item in value.items()
            if key != "_thinkingStarted"
        }

    return value


def normalize_chat(raw_chat, expected_id=None):
    if not isinstance(raw_chat, dict):
        return None

    chat_id = raw_chat.get("id")

    if expected_id is not None and chat_id != expected_id:
        return None

    try:
        validate_chat_id(chat_id)
        created = float(raw_chat["created"])
        updated = float(raw_chat["updated"])
    except (KeyError, TypeError, ValueError, HTTPException):
        return None

    title = raw_chat.get("title")
    messages = raw_chat.get("messages")
    settings = raw_chat.get("settings")
    workspace = raw_chat.get("workspace")

    if not isinstance(title, str) or not isinstance(messages, list):
        return None

    if not all(isinstance(message, dict) for message in messages):
        return None

    if settings is not None and (
        not isinstance(settings, dict) or
        not isinstance(settings.get("system_prompt"), str) or
        not isinstance(settings.get("preset_id"), str)
    ):
        return None

    if workspace is not None and not isinstance(workspace, dict):
        return None

    chat = {
        "id": chat_id,
        "title": title,
        "created": created,
        "updated": updated,
        "messages": messages,
    }

    if settings is not None:
        chat["settings"] = {
            "system_prompt": settings["system_prompt"],
            "preset_id": settings["preset_id"],
        }

        if "temperature" in settings:
            temperature = settings["temperature"]

            if (
                isinstance(temperature, bool) or
                not isinstance(temperature, (int, float)) or
                temperature < 0 or
                temperature > 2
            ):
                return None

            chat["settings"]["temperature"] = float(temperature)

        if "max_tokens" in settings:
            max_tokens = settings["max_tokens"]

            if (
                isinstance(max_tokens, bool) or
                not isinstance(max_tokens, int) or
                max_tokens < 1 or
                max_tokens > 32000
            ):
                return None

            chat["settings"]["max_tokens"] = max_tokens

    if workspace is not None:
        chat["workspace"] = workspace

    return without_streaming_fields(chat)


def read_chat(chat_id):
    path = chat_path(chat_id)

    if not path.exists():
        return None

    try:
        raw_chat = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Chat konnte nicht geladen werden ({chat_id}): {exc}")
        return None

    chat = normalize_chat(raw_chat, expected_id=chat_id)

    if chat is None:
        print(f"Chat hat ein ungültiges Format: {chat_id}")

    return chat


def write_chat(chat):
    path = chat_path(chat["id"])

    try:
        CHAT_DIRECTORY.mkdir(parents=True, exist_ok=True)
        temporary_path = CHAT_DIRECTORY / (
            f".{chat['id']}.{uuid.uuid4().hex}.tmp"
        )
        temporary_path.write_text(
            json.dumps(chat, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Chat konnte nicht gespeichert werden: {exc}",
        )


def list_chats():
    try:
        CHAT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Chat-Verzeichnis konnte nicht erstellt werden: {exc}",
        )

    chats = []

    for path in CHAT_DIRECTORY.glob("*.json"):
        chat_id = path.stem

        if not CHAT_ID_PATTERN.fullmatch(chat_id):
            continue

        chat = read_chat(chat_id)

        if chat is not None:
            chats.append(chat)

    return sorted(
        chats,
        key=lambda chat: chat["updated"],
        reverse=True,
    )


def job_process_is_alive(job):
    """Return whether the manager process recorded for a recovered job lives."""
    pid = job.get("pid")

    if not isinstance(pid, int) or pid <= 0:
        return False

    try:
        os.kill(pid, 0)
    except OSError:
        return False

    try:
        result = subprocess.run(
            ["ps", "-ww", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return False

    command_line = result.stdout.strip()
    command = job.get("command", "")

    return (
        result.returncode == 0
        and str(MLX) in command_line
        and command in command_line
    )


def normalize_job(raw_job, fallback_id=None):
    if not isinstance(raw_job, dict):
        return None

    job_id = str(raw_job.get("id") or fallback_id or "").strip()

    if not job_id:
        return None

    command = raw_job.get("command")
    target = raw_job.get("target")

    if command not in {"download", "retry", "redownload"}:
        return None

    if not isinstance(target, str) or not target.strip():
        return None

    try:
        created_at = float(raw_job.get("created_at", time.time()))
    except (TypeError, ValueError):
        created_at = time.time()

    output = raw_job.get("output")
    if not isinstance(output, list):
        output = []

    return {
        "id": job_id,
        "command": command,
        "target": target.strip(),
        "status": raw_job.get("status", "interrupted"),
        "pid": raw_job.get("pid") if isinstance(raw_job.get("pid"), int) else None,
        "created_at": created_at,
        "started_at": raw_job.get("started_at"),
        "finished_at": raw_job.get("finished_at"),
        "returncode": raw_job.get("returncode"),
        "error": raw_job.get("error"),
        "output": [str(line) for line in output[-500:]],
    }


def save_jobs():
    """Persist a consistent job snapshot without risking a partial JSON file."""
    # All writers serialize snapshot + replace, so an older snapshot cannot resurrect history.
    with JOB_PERSISTENCE_LOCK, JOBS_LOCK:
        try:
            write_jobs_snapshot(list(JOBS.values()))
        except Exception as exc:
            print(f"Job-Persistenz konnte nicht gespeichert werden: {exc}")


def write_jobs_snapshot(jobs):
    payload = {
        "version": 1,
        "saved_at": time.time(),
        "jobs": jobs,
    }

    JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = JOBS_FILE.with_name(
        f".{JOBS_FILE.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        temporary_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_file, JOBS_FILE)
    finally:
        temporary_file.unlink(missing_ok=True)


def recover_job_state(job):
    status = job.get("status")

    if status not in {"queued", "running", "detached"}:
        return False

    if status in {"running", "detached"} and job_process_is_alive(job):
        job["status"] = "detached"
        job["error"] = (
            "Agent wurde neu gestartet; der MLX-Manager-Prozess läuft "
            "weiter und kann nicht mehr live überwacht werden."
        )
        return status != "detached"

    job["status"] = "interrupted"
    job["finished_at"] = job.get("finished_at") or time.time()
    job["error"] = (
        "Agent wurde neu gestartet, bevor dieser Job abgeschlossen "
        "oder weiter überwacht werden konnte."
    )
    return True


def load_jobs():
    if not JOBS_FILE.exists():
        return

    try:
        payload = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Job-Persistenz konnte nicht geladen werden: {exc}")
        return

    if isinstance(payload, dict) and isinstance(payload.get("jobs"), list):
        raw_jobs = payload["jobs"]
    elif isinstance(payload, dict):
    # Accept a dictionary store that may have been used by earlier versions.
        raw_jobs = [
            {**job, "id": job_id}
            for job_id, job in payload.items()
            if isinstance(job, dict)
        ]
    else:
        print("Job-Persistenz hat ein ungültiges Format.")
        return

    recovered = {}
    changed = False

    for raw_job in raw_jobs:
        job = normalize_job(raw_job)
        if not job:
            changed = True
            continue

        changed = recover_job_state(job) or changed
        recovered[job["id"]] = job

    with JOBS_LOCK:
        JOBS.update(recovered)

    if changed:
        save_jobs()


def reconcile_detached_jobs():
    with JOBS_LOCK:
        detached_jobs = [
            job for job in JOBS.values()
            if job.get("status") == "detached"
        ]

    changed = False

    for job in detached_jobs:
        if not job_process_is_alive(job):
            with JOBS_LOCK:
                if job.get("status") == "detached":
                    job["status"] = "interrupted"
                    job["finished_at"] = time.time()
                    job["error"] = (
                        "Der nach Agent-Neustart entkoppelte Prozess ist nicht "
                        "mehr auffindbar; sein Ergebnis ist unbekannt."
                    )
                    changed = True

    if changed:
        save_jobs()


def resolve_repo(target):
    target = target.strip()

    for item in load_models():
        if item["alias"] == target:
            return item["repo"]

    return target


def has_running_job_for_model(target):
    repo = resolve_repo(target)

    aliases = {
        item["alias"]
        for item in load_models()
        if item["repo"] == repo
    }

    candidates = {repo, target, *aliases}

    with JOBS_LOCK:
        for job in JOBS.values():
            if job.get("status") not in {"queued", "running", "detached"}:
                continue

            job_target = job.get("target")

            if job_target in candidates:
                return True, job

    return False, None



def run_background_job(job_id, command, target):
    args = [str(MLX), command]

    if target:
        args.append(target)

    with JOBS_LOCK:
        JOBS[job_id]["status"] = "running"
        JOBS[job_id]["started_at"] = time.time()
    save_jobs()

    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        with JOBS_LOCK:
            JOBS[job_id]["pid"] = process.pid
        save_jobs()

        last_save = time.monotonic()
        if process.stdout:
            for line in process.stdout:
                line = line.rstrip()

                with JOBS_LOCK:
                    JOBS[job_id]["output"].append(line)

                    # Keep the log from growing indefinitely.
                    JOBS[job_id]["output"] = JOBS[job_id]["output"][-500:]

                if time.monotonic() - last_save >= 1:
                    save_jobs()
                    last_save = time.monotonic()

        returncode = process.wait()

        with JOBS_LOCK:
            JOBS[job_id]["returncode"] = returncode
            JOBS[job_id]["finished_at"] = time.time()

            if returncode == 0:
                JOBS[job_id]["status"] = "completed"
            else:
                JOBS[job_id]["status"] = "failed"
        save_jobs()

    except Exception as exc:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"] = str(exc)
            JOBS[job_id]["finished_at"] = time.time()
        save_jobs()



@locked_model_change
def create_hf_subfolder_job(alias, repo, quantization):
    quantization = (quantization or "").strip()

    allowed = {"2-bit", "4-bit", "6-bit", "8-bit"}

    if quantization not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Ungültige Quantisierung: {quantization}",
        )

    running, existing_job = has_running_job_for_model(alias)

    if running:
        raise HTTPException(
            status_code=409,
            detail=f"Für dieses Modell läuft bereits Job {existing_job['id']}.",
        )

    local_root = Path.home() / "Models" / repo.split("/")[-1]
    model_path = local_root / quantization

    job_id = uuid.uuid4().hex[:12]

    job = {
        "id": job_id,
        "command": "download",
        "target": alias,
        "status": "queued",
        "pid": None,
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "returncode": None,
        "error": None,
        "output": [],
        "repo": repo,
        "quantization": quantization,
        "local_path": str(model_path),
    }

    with JOBS_LOCK:
        JOBS[job_id] = job

    save_jobs()

    thread = threading.Thread(
        target=run_hf_subfolder_job,
        args=(job_id, repo, quantization, local_root),
        daemon=True,
    )

    thread.start()

    return job


def run_hf_subfolder_job(job_id, repo, quantization, local_root):
    hf = shutil.which("hf")

    if not hf:
        candidates = [
            "/opt/homebrew/Caskroom/miniforge/base/bin/hf",
            "/opt/homebrew/bin/hf",
        ]

        hf = next(
            (candidate for candidate in candidates if Path(candidate).exists()),
            None,
        )

    if not hf:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"] = "Hugging-Face CLI 'hf' wurde nicht gefunden."
            JOBS[job_id]["finished_at"] = time.time()

        save_jobs()
        return

    local_root.mkdir(parents=True, exist_ok=True)

    args = [
        str(hf),
        "download",
        repo,
        "--include",
        f"{quantization}/*",
        "--local-dir",
        str(local_root),
    ]

    with JOBS_LOCK:
        JOBS[job_id]["status"] = "running"
        JOBS[job_id]["started_at"] = time.time()

    save_jobs()

    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        with JOBS_LOCK:
            JOBS[job_id]["pid"] = process.pid

        save_jobs()

        if process.stdout:
            for line in process.stdout:
                line = line.rstrip()

                with JOBS_LOCK:
                    JOBS[job_id]["output"].append(line)
                    JOBS[job_id]["output"] = JOBS[job_id]["output"][-500:]

        returncode = process.wait()

        with JOBS_LOCK:
            JOBS[job_id]["returncode"] = returncode
            JOBS[job_id]["finished_at"] = time.time()
            JOBS[job_id]["status"] = (
                "completed" if returncode == 0 else "failed"
            )

        save_jobs()

    except Exception as exc:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"] = str(exc)
            JOBS[job_id]["finished_at"] = time.time()

        save_jobs()


@locked_model_change
def create_background_job(command, target=None):
    if command not in {
        "download",
        "retry",
        "redownload",
    }:
        raise HTTPException(
            status_code=400,
            detail="Ungültiger Job-Typ",
        )

    target = (target or "").strip()

    if not target:
        raise HTTPException(
            status_code=400,
            detail="Modell oder Alias fehlt",
        )

    running, job = has_running_job_for_model(target)
    if running:
        raise HTTPException(
            status_code=409,
            detail=f"Für dieses Modell läuft bereits Job {job['id']}.",
        )

    job_id = uuid.uuid4().hex[:12]

    job = {
        "id": job_id,
        "command": command,
        "target": target,
        "status": "queued",
        "pid": None,
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "returncode": None,
        "error": None,
        "output": [],
    }

    with JOBS_LOCK:
        JOBS[job_id] = job
    save_jobs()

    thread = threading.Thread(
        target=run_background_job,
        args=(job_id, command, target),
        daemon=True,
    )

    thread.start()

    return job


@app.get("/api/chats")
def get_chats():
    with CHATS_LOCK:
        return {"chats": list_chats()}


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str):
    with CHATS_LOCK:
        chat = read_chat(chat_id)

    if chat is None:
        raise HTTPException(
            status_code=404,
            detail="Chat nicht gefunden",
        )

    return {"chat": chat}


@app.put("/api/chats/{chat_id}")
def put_chat(chat_id: str, request: ChatSessionRequest):
    validate_chat_id(chat_id)

    if request.id != chat_id:
        raise HTTPException(
            status_code=400,
            detail="Chat-ID im Pfad und Inhalt stimmen nicht überein",
        )

    incoming = normalize_chat(request.model_dump(), expected_id=chat_id)

    if incoming is None:
        raise HTTPException(
            status_code=400,
            detail="Ungültige Chat-Daten",
        )

    with CHATS_LOCK:
        existing = read_chat(chat_id)

        if (
            existing is not None and
            existing["updated"] > incoming["updated"]
        ):
            return {
                "chat": existing,
                "conflict": True,
            }

        write_chat(incoming)

    return {
        "chat": incoming,
        "conflict": False,
    }


def collect_chat_image_ids(value):
    """Collect only valid local image IDs from a chat."""
    found = set()

    def walk(item):
        if isinstance(item, dict):
            image_id = item.get("image_id")

            if (
                isinstance(image_id, str)
                and IMAGE_ID_PATTERN.fullmatch(image_id)
            ):
                found.add(image_id)

            for child in item.values():
                walk(child)

        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return found


def delete_chat_images(chat):
    """Delete local generated images referenced by the chat."""
    deleted = []
    failed = []

    for image_id in collect_chat_image_ids(chat):
        image_path = IMAGE_DIRECTORY / f"{image_id}.png"

        try:
            if image_path.is_file():
                image_path.unlink()
                deleted.append(image_id)
        except Exception as exc:
            failed.append({
                "image_id": image_id,
                "error": str(exc),
            })

    return deleted, failed


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str):
    path = chat_path(chat_id)

    with CHATS_LOCK:
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail="Chat nicht gefunden",
            )

        chat = read_chat(chat_id)

        if chat is None:
            raise HTTPException(
                status_code=500,
                detail="Chat konnte vor dem Löschen nicht gelesen werden",
            )

        deleted_images, failed_images = delete_chat_images(chat)

        try:
            path.unlink()
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Chat konnte nicht gelöscht werden: {exc}",
            )

    return {
        "deleted": chat_id,
        "deleted_images": deleted_images,
        "failed_images": failed_images,
    }


load_jobs()



def load_config():
    config = {}

    if not CONFIG.exists():
        return config

    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        config[key] = value.strip().strip('"')

    return config


def find_server_pid(port: int = 8000):
    """
    Return the PID of the process listening on the configured MLX port.

    Works for both mlx_lm.server and mlx_vlm server runtimes.
    """
    try:
        result = subprocess.run(
            [
                "lsof",
                "-nP",
                f"-iTCP:{int(port)}",
                "-sTCP:LISTEN",
                "-t",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line)

    return None


def system_memory_info():
    total_bytes = None
    free_percent = None
    swap_total_mb = 0.0
    swap_used_mb = 0.0

    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0:
            total_bytes = int(
                result.stdout.strip()
            )
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["memory_pressure"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        output = (
            result.stdout +
            "\n" +
            result.stderr
        )

        for line in output.splitlines():
            if (
                "System-wide memory free percentage:"
                in line
            ):
                value = (
                    line.split(":")[-1]
                    .replace("%", "")
                    .strip()
                )

                free_percent = float(value)

    except Exception:
        pass

    try:
        result = subprocess.run(
            ["sysctl", "-n", "vm.swapusage"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        output = result.stdout.strip()

        import re

        total_match = re.search(
            r"total = ([0-9.]+)M",
            output,
        )

        used_match = re.search(
            r"used = ([0-9.]+)M",
            output,
        )

        if total_match:
            swap_total_mb = float(
                total_match.group(1)
            )

        if used_match:
            swap_used_mb = float(
                used_match.group(1)
            )

    except Exception:
        pass

    return {
        "total_bytes": total_bytes,
        "total_gb": (
            round(
                total_bytes /
                1024 /
                1024 /
                1024,
                2,
            )
            if total_bytes
            else None
        ),
        "free_percent": free_percent,
        "swap_total_mb": swap_total_mb,
        "swap_used_mb": swap_used_mb,
        "swap_total_gb": round(
            swap_total_mb / 1024,
            2,
        ),
        "swap_used_gb": round(
            swap_used_mb / 1024,
            2,
        ),
    }


def mlx_server_args():
    pid = find_server_pid()

    if not pid:
        return []

    try:
        result = subprocess.run(
            [
                "ps",
                "-ww",
                "-o",
                "command=",
                "-p",
                str(pid),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        command = result.stdout.strip()

        if not command:
            return []

        import shlex

        return shlex.split(command)

    except Exception:
        return []



def process_uptime_seconds(pid):
    if not pid:
        return None

    try:
        result = subprocess.run(
            [
                "ps",
                "-o",
                "etime=",
                "-p",
                str(pid),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        value = result.stdout.strip()

        if not value:
            return None

        days = 0

        if "-" in value:
            days_part, value = (
                value.split("-", 1)
            )

            days = int(days_part)

        parts = [
            int(part)
            for part in
            value.split(":")
        ]

        if len(parts) == 3:
            hours, minutes, seconds = parts

        elif len(parts) == 2:
            hours = 0
            minutes, seconds = parts

        else:
            return None

        return (
            days * 86400 +
            hours * 3600 +
            minutes * 60 +
            seconds
        )

    except Exception:
        return None



def collect_log_sources(limit=200):
    sources = []

    def add_log(source_id, name, log_file):
        if not log_file.exists():
            return

        try:
            content = log_file.read_text(
                encoding="utf-8",
                errors="replace",
            )

            # Remove null bytes from old or malformed logs.
            content = content.replace("\x00", "")

            lines = content.splitlines()

            sources.append({
                "id": source_id,
                "name": name,
                "file": str(log_file),
                "lines": lines[-limit:],
            })

        except Exception as exc:
            sources.append({
                "id": source_id,
                "name": name,
                "file": str(log_file),
                "lines": [
                    f"Log konnte nicht gelesen werden: {exc}"
                ],
            })


    # MLX Runtime
    add_log(
        "mlx-server",
        "MLX Server",
        Path.home()
        / ".config/mlx-server/server.log",
    )

    add_log(
        "mlx-errors",
        "MLX Errors",
        Path.home()
        / ".config/mlx-server/server-error.log",
    )

    # Web-Agent
    add_log(
        "agent",
        "MLX Agent",
        Path.home()
        / "mlx-web/agent.log",
    )


    # Downloads / Hintergrundjobs
    job_lines = []

    with JOBS_LOCK:
        jobs = list(JOBS.values())

    jobs.sort(
        key=lambda item:
            item.get("created_at", 0)
    )

    for job in jobs[-20:]:

        job_lines.append(
            f"[{job.get('status', '?')}] "
            f"{job.get('command', '?')} "
            f"{job.get('target', '')} "
            f"(Job {job.get('id', '?')})"
        )

        for line in (
            job.get("output") or []
        )[-50:]:

            job_lines.append(
                "  " + str(line)
            )

        if job.get("error"):
            job_lines.append(
                "  ERROR: " +
                str(job["error"])
            )

        job_lines.append("")

    sources.append({
        "id": "jobs",
        "name": "Downloads & Jobs",
        "file": "Job Store",
        "lines": job_lines[-limit:],
    })

    return sources


def mlx_log_lines(limit=150):
    candidates = [
        Path.home() / ".config/mlx-server/server.log",
        Path.home() / "mlx-server.log",
        Path.home() / "Library/Logs/mlx-server.log",
        Path.home() / "mlx-web/agent.log",
    ]

    found = []

    for log_file in candidates:
        if not log_file.exists():
            continue

        try:
            lines = log_file.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()

            found.append({
                "file": str(log_file),
                "lines": lines[-limit:],
            })

        except Exception:
            continue

    return found



def process_memory_mb(pid):
    if not pid:
        return 0.0

    result = subprocess.run(
        ["ps", "-o", "rss=", "-p", str(pid)],
        capture_output=True,
        text=True,
    )

    try:
        rss_kb = int(result.stdout.strip())
        return round(rss_kb / 1024, 2)
    except (ValueError, TypeError):
        return 0.0


def mlx_api_online(port):
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/v1/models",
            timeout=2,
        ) as response:
            return response.status == 200

    except (urllib.error.URLError, TimeoutError):
        return False



def detect_model_metadata(repo):
    repo = str(repo or "").strip()

    metadata = {
        "backend": "lm",
        "vision": False,
        "local": repo.startswith("/"),
        "available": None,
        "quantization": None,
    }

    # Infer quantization from the path or repository name.
    lower_repo = repo.lower()

    quant_patterns = (
        ("8-bit", ("8-bit", "8bit")),
        ("6.4-bit", ("6.4-bit", "6.4bit")),
        ("6-bit", ("6-bit", "6bit")),
        ("5-bit", ("5-bit", "5bit")),
        ("4-bit", ("4-bit", "4bit")),
        ("3-bit", ("3-bit", "3bit")),
        ("2-bit", ("2-bit", "2bit")),
    )

    for label, patterns in quant_patterns:
        if any(pattern in lower_repo for pattern in patterns):
            metadata["quantization"] = label
            break

    # Local model: inspect config.json.
    model_path = Path(repo).expanduser()

    if metadata["local"]:
        metadata["available"] = model_path.is_dir()

    if model_path.is_dir():
        config_path = model_path / "config.json"

        if config_path.exists():
            try:
                config = json.loads(
                    config_path.read_text(
                        encoding="utf-8"
                    )
                )

                vision_config = config.get("vision_config")
                architectures = config.get("architectures") or []
                model_type = str(
                    config.get("model_type", "")
                ).lower()

                architecture_text = " ".join(
                    str(item)
                    for item in architectures
                ).lower()

                is_vlm = (
                    vision_config is not None
                    or "vision" in architecture_text
                    or "conditionalgeneration" in architecture_text
                    or "_vl" in model_type
                    or "-vl" in model_type
                )

                if is_vlm:
                    metadata["backend"] = "vlm"
                    metadata["vision"] = True

            except Exception:
                pass

    return metadata


def load_models():
    models = []

    if not MODELS.exists():
        return models

    for line in MODELS.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        alias, repo = line.split("=", 1)

        alias = alias.strip()
        repo = repo.strip()

        if not alias or not repo:
            continue

        metadata = detect_model_metadata(repo)

        models.append({
            "alias": alias,
            "repo": repo,
            **metadata,
        })

    return models



def run_mlx_command(command):
    if command not in {"start", "stop", "restart", "reset"}:
        raise HTTPException(
            status_code=400,
            detail="Ungültiger MLX-Befehl",
        )

    if not MLX.exists():
        raise HTTPException(
            status_code=500,
            detail=f"MLX Manager fehlt: {MLX}",
        )

    try:
        result = subprocess.run(
            [str(MLX), command],
            capture_output=True,
            text=True,
            timeout=180,
        )

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail=f"mlx {command} Timeout",
        )

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "command": command,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            },
        )

    return {
        "ok": True,
        "command": command,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


@app.get("/")
def root():
    return {
        "name": "MLX macOS Agent",
        "status": "running",
    }


@app.get("/api/system")
def system():
    config = load_config()

    port = int(
        config.get("PORT", "8000")
    )

    pid = find_server_pid()

    memory = system_memory_info()

    return {
        "mlx": {
            "pid": pid,
            "port": port,
            "model": config.get("MODEL"),
            "thinking": (
                config
                .get("THINKING", "false")
                .lower()
                == "true"
            ),
            "memory_mb": process_memory_mb(
                pid
            ),
            "uptime_seconds":
                process_uptime_seconds(
                    pid
                ),
            "server_args":
                mlx_server_args(),
        },
        "system": memory,
    }


@app.get("/api/logs/all")
def logs_all(limit: int = 200):
    limit = max(
        20,
        min(limit, 1000),
    )

    return {
        "sources":
            collect_log_sources(
                limit
            )
    }



@app.get("/api/logs")
def logs(limit: int = 150):
    limit = max(
        20,
        min(limit, 1000),
    )

    return {
        "logs": mlx_log_lines(
            limit
        )
    }



@app.get("/api/status")
def status():
    config = load_config()

    model = config.get("MODEL")
    port = int(config.get("PORT", "8000"))
    thinking = config.get("THINKING", "false").lower() == "true"

    pid = find_server_pid(port)
    online = mlx_api_online(port)

    return {
        "online": online,
        "model": model,
        "thinking": thinking,
        "port": port,
        "pid": pid,
        "memory_mb": process_memory_mb(pid),
    }



def _service_health(name, url, port, detail_getter=None):
    started = time.perf_counter()

    try:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json"},
            method="GET",
        )

        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.loads(
                response.read().decode("utf-8")
            )

        latency_ms = round(
            (time.perf_counter() - started) * 1000
        )

        detail = None

        if detail_getter:
            try:
                detail = detail_getter(payload)
            except Exception:
                detail = None

        return {
            "name": name,
            "online": True,
            "port": port,
            "latency_ms": latency_ms,
            "detail": detail,
            "status": payload.get("status"),
        }

    except Exception as exc:
        latency_ms = round(
            (time.perf_counter() - started) * 1000
        )

        return {
            "name": name,
            "online": False,
            "port": port,
            "latency_ms": latency_ms,
            "detail": None,
            "error": str(exc),
        }


def _service_model_name(value):
    if not value:
        return None

    parts = str(value).rstrip("/").split("/")

    if parts[-1].lower() in {
        "4-bit",
        "6-bit",
        "8-bit",
        "4bit",
        "6bit",
        "8bit",
    } and len(parts) >= 2:
        return parts[-2]

    return parts[-1]


@app.get("/api/services/health")
def services_health():
    config = load_config()
    runtime_port = int(
        config.get("PORT", "8000")
    )

    runtime_started = time.perf_counter()
    runtime_pid = find_server_pid(runtime_port)
    runtime_online = mlx_api_online(runtime_port)

    services = [
        {
            "name": "MLX Runtime",
            "online": runtime_online,
            "port": runtime_port,
            "latency_ms": round(
                (time.perf_counter() - runtime_started) * 1000
            ),
            "detail": _service_model_name(
                config.get("MODEL")
            ),
            "pid": runtime_pid,
            "memory_mb": process_memory_mb(runtime_pid),
        }
    ]

    services.append(
        _service_health(
            "Agent",
            "http://127.0.0.1:8010/api/status",
            8010,
            lambda data: _service_model_name(
                data.get("model")
            ),
        )
    )

    services.append(
        _service_health(
            "Router",
            f"{ROUTER_URL}/health",
            8040,
            lambda data: _service_model_name(
                data.get("loaded_model")
            ),
        )
    )

    services.append(
        _service_health(
            "Speech",
            "http://127.0.0.1:8050/health",
            8050,
            lambda data: _service_model_name(
                data.get("model")
            ),
        )
    )

    services.append(
        _service_health(
            "Embeddings",
            "http://127.0.0.1:8020/health",
            8020,
            lambda data: " · ".join(
                str(item)
                for item in (
                    _service_model_name(
                        data.get("model")
                    ),
                    data.get("backend"),
                    data.get("device"),
                )
                if item
            ),
        )
    )

    services.append(
        _service_health(
            "Images",
            f"{IMAGE_SERVICE_URL}/health",
            8030,
            lambda data: " · ".join(
                str(item)
                for item in (
                    data.get("backend"),
                    data.get("running_model")
                    or data.get("default_model"),
                )
                if item
            ),
        )
    )

    return {
        "ok": True,
        "services": services,
    }


@app.post("/api/server/{command}")
def server_command(command: str):
    acquired = MODEL_RUNTIME_LOCK.acquire(blocking=False)

    if not acquired:
        raise HTTPException(
            status_code=409,
            detail="Eine andere Runtime-Aktion läuft bereits.",
        )

    try:
        return run_mlx_command(command)
    finally:
        MODEL_RUNTIME_LOCK.release()


def human_size(num_bytes):
    value = float(num_bytes)

    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            if unit in {"GB", "TB"}:
                return f"{value:.2f} {unit}"
            return f"{value:.1f} {unit}"

        value /= 1024


def directory_size(path):
    """
    Count the actual files stored in the Hugging Face cache.

    Deliberately ignore snapshot symlinks because they point to files under
    blobs/ and would otherwise be counted twice.
    """
    total = 0

    try:
        for item in path.rglob("*"):

            try:
                if item.is_symlink():
                    continue

                if item.is_file():
                    total += item.stat().st_size

            except OSError:
                continue

    except OSError:
        pass

    return total


def load_cache():
    base = Path.home() / ".cache/huggingface/hub"
    models = load_models()
    alias_by_repo = {
        item["repo"]: item["alias"]
        for item in models
    }

    local_models = []
    with JOBS_LOCK:
        jobs_snapshot = [dict(job) for job in JOBS.values()]

    for model in models:
        if not model.get("local"):
            continue

        raw_path = str(model.get("repo") or "").strip()
        if not raw_path:
            continue

        try:
            model_path = Path(raw_path).expanduser().resolve()
            root = LOCAL_MODELS_ROOT.expanduser().resolve()
            relative = model_path.relative_to(root)
        except (OSError, ValueError):
            continue

        exact_repos = set()
        for job in jobs_snapshot:
            local_path = str(job.get("local_path") or "").strip()
            source_repo = str(job.get("repo") or "").strip()
            if not local_path or not source_repo:
                continue
            try:
                if Path(local_path).expanduser().resolve() == model_path:
                    exact_repos.add(source_repo)
            except OSError:
                continue

        local_models.append({
            "alias": model.get("alias"),
            "path": str(model_path),
            "root_name": relative.parts[0] if relative.parts else model_path.name,
            "exact_repos": exact_repos,
            "size_bytes": directory_size(model_path) if model_path.exists() else 0,
        })

    result = []
    if not base.exists():
        return result

    for directory in sorted(base.glob("models--*")):
        if not directory.is_dir():
            continue

        repo = directory.name.removeprefix("models--").replace("--", "/")
        incomplete_candidates = list(directory.rglob("*.incomplete"))

        incomplete = []
        for file in incomplete_candidates:
            base_hash = file.name.split(".", 1)[0]
            completed_blob = file.parent / base_hash
            if not completed_blob.exists():
                incomplete.append(file)

        size_bytes = directory_size(directory)
        incomplete_bytes = 0
        for file in incomplete:
            try:
                incomplete_bytes += file.stat().st_size
            except OSError:
                pass

        complete = len(incomplete) == 0
        repo_name = repo.split("/")[-1]

        exact_matches = []
        possible_matches = []

        if complete and size_bytes >= 10 * 1024 * 1024:
            for local in local_models:
                match = {
                    "alias": local["alias"],
                    "path": local["path"],
                    "size_bytes": local["size_bytes"],
                    "size": human_size(local["size_bytes"]),
                }

                if repo in local["exact_repos"]:
                    match["match"] = "exact"
                    exact_matches.append(match)
                elif local["root_name"] == repo_name:
                    match["match"] = "name"
                    possible_matches.append(match)

        matches = exact_matches or possible_matches
        duplicate = bool(exact_matches)
        possible_duplicate = not duplicate and bool(possible_matches)

        duplicate_size_bytes = 0
        if duplicate and exact_matches:
            local_size = max(item["size_bytes"] for item in exact_matches)
            duplicate_size_bytes = min(size_bytes, local_size) if local_size else size_bytes

        result.append({
            "repo": repo,
            "alias": alias_by_repo.get(repo),
            "path": str(directory),
            "size_bytes": size_bytes,
            "size": human_size(size_bytes),
            "complete": complete,
            "incomplete_files": len(incomplete),
            "incomplete_bytes": incomplete_bytes,
            "incomplete_size": human_size(incomplete_bytes),
            "duplicate": duplicate,
            "possible_duplicate": possible_duplicate,
            "duplicate_size_bytes": duplicate_size_bytes,
            "duplicate_size": human_size(duplicate_size_bytes),
            "local_matches": matches,
        })

    return result


@app.get("/api/models/select-folder")
def select_model_folder():
    if sys.platform != "darwin":
        raise HTTPException(
            status_code=501,
            detail="Die Ordnerauswahl wird derzeit nur unter macOS unterstützt.",
        )

    script = """
    try
        set selectedFolder to choose folder with prompt "MLX-Modellordner auswählen"
        return POSIX path of selectedFolder
    on error number -128
        return ""
    end try
    """

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=504,
            detail="Ordnerauswahl wurde nicht abgeschlossen.",
        ) from exc

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=result.stderr.strip() or "Ordnerauswahl fehlgeschlagen.",
        )

    path = result.stdout.strip()

    if not path:
        return {"cancelled": True, "path": None}

    folder = Path(path).expanduser().resolve()

    if not folder.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Der ausgewählte Pfad ist kein Ordner.",
        )

    model_markers = (
        "config.json",
        "model.safetensors",
        "model.safetensors.index.json",
        "tokenizer.json",
        "tokenizer_config.json",
    )

    detected = [
        name
        for name in model_markers
        if (folder / name).exists()
    ]

    has_safetensors = any(folder.glob("*.safetensors"))

    return {
        "cancelled": False,
        "path": str(folder),
        "looks_like_model": bool(detected or has_safetensors),
        "detected": detected,
    }


def validate_model_reference(value):
    """The legacy manager writes shell config: reject shell/sed/awk metacharacters.

    Spaces and Unicode in local directories remain supported. Remote references
    must be Hugging Face owner/repository IDs, never command options.
    """
    if not value or any(ord(char) < 32 or ord(char) == 127 or char in '\\"`$|&' for char in value):
        raise HTTPException(400, "Modellreferenz enthält unsichere Zeichen")
    if value.startswith(("/", "~/")):
        return str(Path(value).expanduser())
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*/[A-Za-z0-9_][A-Za-z0-9_.-]*", value):
        raise HTTPException(400, "Erwartet wird owner/model oder ein absoluter Modellpfad")
    return value


@app.post("/api/models/add")
@locked_model_change
def add_model(request: AddModelRequest):
    alias = request.alias.strip()
    repo = validate_model_reference(request.repo.strip())

    if not alias:
        raise HTTPException(
            status_code=400,
            detail="Alias fehlt",
        )

    if not repo:
        raise HTTPException(
            status_code=400,
            detail="Repository fehlt",
        )

    # The manager uses a positional argument, not an option parser. Preserve
    # existing aliases such as _local and -local and the original length policy.
    if not re.fullmatch(r"[A-Za-z0-9._-]+", alias):
        raise HTTPException(
            status_code=400,
            detail="Alias darf nur Buchstaben, Zahlen, Punkt, Unterstrich und Bindestrich enthalten",
        )

    if "/" not in repo:
        raise HTTPException(
            status_code=400,
            detail="Repository muss z. B. mlx-community/Modellname entsprechen",
        )

    existing = load_models()

    for item in existing:
        if item["alias"] == alias:
            raise HTTPException(
                status_code=409,
                detail=f"Alias bereits vorhanden: {alias}",
            )

    quantization = (request.quantization or "").strip()

    if quantization:
        if repo.startswith("/"):
            raise HTTPException(400, "Quantisierungs-Download benötigt ein Hugging-Face-Repository")
        allowed_quantizations = {"2-bit", "4-bit", "6-bit", "8-bit"}

        if quantization not in allowed_quantizations:
            raise HTTPException(
                status_code=400,
                detail=f"Ungültige Quantisierung: {quantization}",
            )

        local_root = Path.home() / "Models" / repo.split("/")[-1]
        model_target = str(local_root / quantization)
    else:
        model_target = repo

    result = subprocess.run(
        [str(MLX), "model", "add", alias, model_target],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            },
        )

    if quantization:
        job = create_hf_subfolder_job(
            alias,
            repo,
            quantization,
        )
    elif Path(model_target).expanduser().is_dir():
        job = None
    else:
        job = create_background_job(
            "download",
            alias,
        )

    return {
        "ok": True,
        "alias": alias,
        "repo": repo,
        "job": job,
        "stdout": result.stdout.strip(),
    }




# ---------------------------------------------------------
# Model roles
# ---------------------------------------------------------

MODEL_ROLES_FILE = (
    Path.home()
    / ".config"
    / "mlx-web"
    / "model-roles.json"
)

MODEL_ROLE_NAMES = (
    "chat",
    "agent",
    "coding",
    "vision",
    "embedding",
    "image",
)

DEFAULT_MODEL_ROLES = {
    role: "auto"
    for role in MODEL_ROLE_NAMES
}


def load_model_roles(strict=False):
    """Load persistent model-role preferences."""
    try:
        if MODEL_ROLES_FILE.is_file():
            data = json.loads(
                MODEL_ROLES_FILE.read_text(
                    encoding="utf-8"
                )
            )
        else:
            data = {}
        if not isinstance(data, dict):
            raise ValueError('Ungültige Modellrollen')
    except Exception as exc:
        if strict:
            raise HTTPException(409, 'Modellrollen nicht sicher lesbar; Löschung blockiert.') from exc
        data = {}

    return {
        role: (
            str(data.get(role, "auto")).strip()
            or "auto"
        )
        for role in MODEL_ROLE_NAMES
    }


def save_model_roles(roles):
    """Persist model-role preferences atomically."""
    MODEL_ROLES_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    normalized = {
        role: (
            str(roles.get(role, "auto")).strip()
            or "auto"
        )
        for role in MODEL_ROLE_NAMES
    }

    temporary = MODEL_ROLES_FILE.with_suffix(
        ".tmp"
    )

    temporary.write_text(
        json.dumps(
            normalized,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(MODEL_ROLES_FILE)

    return normalized


def resolve_model_role(role):
    """
    Resolve a configured role.

    For now this only resolves configuration.
    It deliberately does NOT start or switch models.
    """
    if role not in MODEL_ROLE_NAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Unbekannte Modellrolle: {role}",
        )

    roles = load_model_roles()
    configured = roles[role]

    if role == "image":
        try:
            data = image_api.request("GET", "/models")
            selected_id = data["default_model"] if configured == "auto" else configured
            selected = next((m for m in data["models"] if m["id"] == selected_id), None)
            available = bool(selected and selected["enabled"] and selected["available"])
            return {"role": "image", "configured": configured, "image_model_id": selected_id,
                    "alias": selected_id, "repo": selected.get("repository") if selected else None,
                    "provider": selected.get("provider") if selected else None,
                    "available": available, "active": available, "requires_switch": False}
        except HTTPException:
            return {"role": "image", "configured": configured, "image_model_id": None,
                    "available": False, "active": False, "requires_switch": False,
                    "error": "Image-Service nicht erreichbar"}

    config = load_config()
    current_repo = config.get("MODEL")

    models = load_models()

    current_alias = next(
        (
            item.get("alias")
            for item in models
            if item.get("repo") == current_repo
        ),
        None,
    )

    if configured == "auto":
        if role == "vision":
            selected = next(
                (
                    item
                    for item in models
                    if item.get("vision") is True
                    and item.get("available") is not False
                ),
                None,
            )

            if selected is None:
                return {
                    "role": role,
                    "configured": "auto",
                    "alias": None,
                    "repo": None,
                    "backend": "vlm",
                    "vision": True,
                    "available": False,
                    "active": False,
                    "requires_switch": False,
                    "error": "Kein verfügbares Vision-Modell gefunden",
                }

            selected_repo = selected.get("repo")
            selected_alias = selected.get("alias")

            return {
                "role": role,
                "configured": "auto",
                "alias": selected_alias,
                "repo": selected_repo,
                "backend": selected.get("backend") or "vlm",
                "vision": True,
                "available": selected.get("available") is not False,
                "active": selected_repo == current_repo,
                "requires_switch": selected_repo != current_repo,
            }

        return {
            "role": role,
            "configured": "auto",
            "alias": current_alias,
            "repo": current_repo,
            "active": True,
            "requires_switch": False,
        }

    selected = next(
        (
            item
            for item in models
            if item.get("alias") == configured
        ),
        None,
    )

    if selected is None:
        return {
            "role": role,
            "configured": configured,
            "alias": configured,
            "repo": None,
            "active": False,
            "requires_switch": True,
            "available": False,
        }

    return {
        "role": role,
        "configured": configured,
        "alias": selected.get("alias"),
        "repo": selected.get("repo"),
        "active": (
            selected.get("repo") == current_repo
        ),
        "requires_switch": (
            selected.get("repo") != current_repo
        ),
        "available": True,
    }


@app.get("/api/model-roles")
def get_model_roles():
    roles = load_model_roles()

    return {
        "roles": roles,
        "resolved": {
            role: resolve_model_role(role)
            for role in MODEL_ROLE_NAMES
        },
    }


@app.put("/api/model-roles/{role}")
@locked_model_change
def set_model_role(role: str, request: dict):
    if role not in MODEL_ROLE_NAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Unbekannte Modellrolle: {role}",
        )

    alias = str(
        request.get("alias", "auto")
    ).strip() or "auto"

    if role == "image":
        if alias != "auto":
            selected = image_api.request("GET", "/models/" + image_api.model_id(alias))
            if not selected["enabled"] or not selected["available"]:
                raise HTTPException(409, "Image-Modell ist deaktiviert oder nicht lokal verfügbar")
        roles = load_model_roles()
        roles["image"] = alias
        save_model_roles(roles)
        return {"ok": True, "roles": roles, "resolved": resolve_model_role("image")}

    if alias != "auto":
        models = load_models()

        if not any(
            item.get("alias") == alias
            for item in models
        ):
            raise HTTPException(
                status_code=404,
                detail=(
                    "Unbekanntes Modell-Alias: "
                    + alias
                ),
            )

    roles = load_model_roles()
    roles[role] = alias

    save_model_roles(roles)

    return {
        "ok": True,
        "roles": roles,
        "resolved": resolve_model_role(role),
    }


@app.get("/api/models")
def models():
    config = load_config()
    current_model = config.get("MODEL")

    items = load_models()

    for item in items:
        item["active"] = item["repo"] == current_model

    return {
        "current": current_model,
        "models": items,
    }


@app.get("/api/cache")
def cache():
    items = load_cache()
    cache_path = Path.home() / ".cache/huggingface/hub"
    total_size_bytes = sum(
        item.get("size_bytes", 0)
        for item in items
    )

    config = load_config()
    current_model = config.get("MODEL")

    for item in items:
        item["active"] = item["repo"] == current_model

    return {
        "count": len(items),
        "complete": sum(
            1 for item in items
            if item["complete"]
        ),
        "incomplete": sum(
            1 for item in items
            if not item["complete"]
        ),
        "current_model": current_model,
        "path": str(cache_path),
        "total_size_bytes": total_size_bytes,
        "total_size": human_size(total_size_bytes),
        "models": items,
    }



@app.delete("/api/models/{alias}")
@locked_model_change
def remove_model_alias(alias: str):
    config = load_config()
    current_model = config.get("MODEL")

    models = load_models()

    selected = next(
        (item for item in models if item["alias"] == alias),
        None,
    )

    if selected is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unbekanntes Modell-Alias: {alias}",
        )

    if selected["repo"] == current_model:
        raise HTTPException(
            status_code=409,
            detail="Das aktuell aktive Modell kann nicht entfernt werden.",
        )

    result = subprocess.run(
        [str(MLX), "model", "remove", alias],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            },
        )

    return {
        "ok": True,
        "alias": alias,
        "repo": selected["repo"],
        "stdout": result.stdout.strip(),
    }


def remove_deleted_model_alias(alias):
    remove_model_alias(alias)
    if any(item['alias'] == alias for item in load_models()):
        raise HTTPException(500, 'MLX-Manager hat den Alias nicht entfernt; Modelldateien bleiben erhalten.')


def restore_deleted_model_alias(alias, repo):
    existing = next((item for item in load_models() if item['alias'] == alias), None)
    if existing:
        if existing['repo'] == repo:
            return
        raise HTTPException(409, "Alias wurde zwischenzeitlich verändert: " + alias)
    result = subprocess.run([str(MLX), 'model', 'add', alias, repo],
                            capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise HTTPException(500, "Restdaten erhalten, Alias konnte nicht wiederhergestellt werden: " + alias)


@app.delete('/api/models/{alias}/local')
@locked_model_change
def delete_local_model(alias: str):
    if not re.fullmatch(r'[A-Za-z0-9._-]+', alias):
        raise HTTPException(400, "Ungültiger Modellalias")
    library = load_models()
    selected = next((item for item in library if item['alias'] == alias), None)
    if selected is None:
        raise HTTPException(404, "Unbekanntes Modell-Alias: " + alias)
    running, job = has_running_job_for_model(alias)
    if running:
        raise HTTPException(409, f"Modell wird von Download {job['id']} verwendet.")
    config = load_config()
    if not config.get('MODEL'):
        raise HTTPException(409, 'Aktive Modellkonfiguration nicht sicher bestimmbar; Löschung blockiert.')
    protected = [config.get('MODEL'), ROUTER_MODEL]
    # A download can retain its destination after its alias was changed/removed.
    with JOBS_LOCK:
        protected.extend(job.get('local_path') for job in JOBS.values()
                         if job.get('status') in {'queued', 'running', 'detached'}
                         or recorded_process_alive(job))
    args = mlx_server_args()
    runtime_models = []
    for index, arg in enumerate(args):
        if arg == '--model' and index + 1 < len(args):
            runtime_models.append(args[index + 1])
        elif arg.startswith('--model='):
            runtime_models.append(arg.split('=', 1)[1])
    if find_server_pid(int(config.get('PORT', 8000))) and not any(runtime_models):
        raise HTTPException(409, 'Laufende Runtime nicht sicher prüfbar; Löschung blockiert.')
    protected.extend(runtime_models)
    try:
        return model_cleanup.delete_local_model(
            alias, library, LOCAL_MODELS_ROOT, protected, load_model_roles(strict=True),
            remove_deleted_model_alias, restore_deleted_model_alias,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, "MLX-Manager hat nicht rechtzeitig geantwortet; Alias und Modellpfad prüfen.") from exc


@app.post('/api/jobs/cleanup')
def cleanup_download_history(request: HistoryCleanupRequest):
    statuses = history_statuses(request.scope)
    with JOB_PERSISTENCE_LOCK, JOBS_LOCK:
        removable = {key for key, job in JOBS.items()
                     if job.get('status') in statuses and not recorded_process_alive(job)}
        remaining = {key: job for key, job in JOBS.items() if key not in removable}
        try:
            if removable:
                write_jobs_snapshot(list(remaining.values()))
        except OSError as exc:
            raise HTTPException(500, "Download-Historie konnte nicht gespeichert werden.") from exc
        for key in removable:
            del JOBS[key]
    return {'ok': True, 'removed': len(removable), 'remaining': len(remaining)}


def recorded_process_alive(job):
    pid = job.get('pid')
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True  # Permission/inspection failures must never authorize cleanup.



@app.delete("/api/cache/{target:path}")
def delete_cache(target: str):
    target = target.strip()

    if not target:
        raise HTTPException(
            status_code=400,
            detail="Modell oder Alias fehlt",
        )

    models = load_models()

    selected = next(
        (
            item
            for item in models
            if item["alias"] == target
        ),
        None,
    )

    repo = (
        selected["repo"]
        if selected
        else target
    )

    config = load_config()
    current_model = config.get("MODEL")

    if repo == current_model:
        raise HTTPException(
            status_code=409,
            detail="Der Cache des aktuell aktiven Modells kann nicht gelöscht werden.",
        )

    running, job = has_running_job_for_model(target)

    if running:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cache kann nicht gelöscht werden, "
                f"solange Job {job['id']} läuft."
            ),
        )

    cache_dir = (
        Path.home()
        / ".cache/huggingface/hub"
        / ("models--" + repo.replace("/", "--"))
    )

    if not cache_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Modell nicht im Cache gefunden: {repo}",
        )

    try:
        result = subprocess.run(
            [str(MLX), "remove", target, "--yes"],
            capture_output=True,
            text=True,
            timeout=300,
        )

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail=f"Cache-Löschung Timeout: {target}",
        )

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            },
        )

    return {
        "ok": True,
        "target": target,
        "repo": repo,
        "stdout": result.stdout.strip(),
    }



@app.post("/api/model/{alias}")
def model_command(alias: str):
    acquired = MODEL_RUNTIME_LOCK.acquire(blocking=False)

    if not acquired:
        raise HTTPException(
            status_code=409,
            detail="Eine andere Runtime-Aktion läuft bereits.",
        )

    try:
        return run_model_command(alias)
    finally:
        MODEL_RUNTIME_LOCK.release()


def run_model_command(alias: str):
    """
    HTTP-facing adapter for the shared MLX runtime switcher.

    The switch is only reported as successful after the requested model
    is configured and the MLX API is responding.
    """
    try:
        return switch_model_runtime(alias)
    except RuntimeError as exc:
        message = str(exc)

        if message.startswith("Unbekanntes Modell-Alias:"):
            raise HTTPException(
                status_code=404,
                detail=message,
            ) from exc

        if message.startswith("Modellwechsel Timeout:"):
            raise HTTPException(
                status_code=504,
                detail=message,
            ) from exc

        if "wurde nicht innerhalb von" in message:
            raise HTTPException(
                status_code=504,
                detail=message,
            ) from exc

        raise HTTPException(
            status_code=500,
            detail=message,
        ) from exc


@app.post("/api/download/{target:path}")
def download_model(target: str):
    target = target.strip()

    if not target:
        raise HTTPException(
            status_code=400,
            detail="Modell oder Alias fehlt",
        )

    try:
        result = subprocess.run(
            [str(MLX), "download", target],
            capture_output=True,
            text=True,
            timeout=7200,
        )

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail=f"Download Timeout: {target}",
        )

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "target": target,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            },
        )

    return {
        "ok": True,
        "target": target,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


@app.post("/api/retry/{target:path}")
def retry_download(target: str):
    target = target.strip()

    if not target:
        raise HTTPException(
            status_code=400,
            detail="Modell oder Alias fehlt",
        )

    try:
        result = subprocess.run(
            [str(MLX), "retry", target],
            capture_output=True,
            text=True,
            timeout=7200,
        )

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail=f"Retry Timeout: {target}",
        )

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "target": target,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            },
        )

    return {
        "ok": True,
        "target": target,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }



@app.get("/api/jobs")
def list_jobs():
    reconcile_detached_jobs()

    with JOBS_LOCK:
        jobs = list(JOBS.values())

    jobs.sort(
        key=lambda item: item["created_at"],
        reverse=True,
    )

    return {
        "jobs": jobs,
    }


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    reconcile_detached_jobs()

    with JOBS_LOCK:
        job = JOBS.get(job_id)

        if job is None:
            raise HTTPException(
                status_code=404,
                detail="Job nicht gefunden",
            )

        return job


@app.post("/api/jobs/download/{target:path}")
def start_download_job(target: str):
    return create_background_job(
        "download",
        target.strip(),
    )


@app.post("/api/jobs/retry/{target:path}")
def start_retry_job(target: str):
    return create_background_job(
        "retry",
        target.strip(),
    )


@app.post("/api/jobs/redownload-safe/{target:path}")
def start_safe_redownload_job(target: str):
    target = target.strip()

    if not target:
        raise HTTPException(
            status_code=400,
            detail="Modell oder Alias fehlt",
        )

    repo = resolve_repo(target)

    config = load_config()
    current_model = config.get("MODEL")

    if repo == current_model:
        raise HTTPException(
            status_code=409,
            detail="Das aktuell aktive Modell kann nicht neu heruntergeladen werden.",
        )

    running, job = has_running_job_for_model(target)

    if running:
        raise HTTPException(
            status_code=409,
            detail=f"Für dieses Modell läuft bereits Job {job['id']}.",
        )

    return create_background_job(
        "redownload",
        target,
    )



@app.post("/api/jobs/redownload/{target:path}")
def start_redownload_job(target: str):
    # Legacy route retained for compatibility and protected by the same
    # safeguards as the safe route used by the web backend.
    return start_safe_redownload_job(target)



@app.post("/api/thinking/{state}")
def thinking_command(state: str):
    acquired = MODEL_RUNTIME_LOCK.acquire(blocking=False)

    if not acquired:
        raise HTTPException(
            status_code=409,
            detail="Eine andere Runtime-Aktion läuft bereits.",
        )

    try:
        return run_thinking_command(state)
    finally:
        MODEL_RUNTIME_LOCK.release()


def run_thinking_command(state: str):
    if state not in {"on", "off"}:
        raise HTTPException(
            status_code=400,
            detail="Thinking muss on oder off sein",
        )

    try:
        result = subprocess.run(
            [str(MLX), "thinking", state],
            capture_output=True,
            text=True,
            timeout=180,
        )

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="Thinking-Umschaltung Timeout",
        )

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            },
        )

    return {
        "ok": True,
        "thinking": state == "on",
        "stdout": result.stdout.strip(),
    }


# ============================================================
# MLX Chat Notes
# ============================================================

NOTES_FILE = Path.home() / ".config/mlx-web/notes.json"
NOTES_LOCK = threading.Lock()


class NoteRequest(BaseModel):
    name: str
    content: str
    folder_id: str | None = None


class NoteMoveRequest(BaseModel):
    folder_id: str | None = None


class NoteFolderRequest(BaseModel):
    name: str
    parent_id: str | None = None


class NoteFolderUpdateRequest(BaseModel):
    name: str | None = None
    parent_id: str | None = None
    collapsed: bool | None = None


def load_notes_data():
    if not NOTES_FILE.exists():
        return {
            "folders": [],
            "notes": [],
        }

    try:
        data = json.loads(
            NOTES_FILE.read_text(encoding="utf-8")
        )

        # Automatically migrate the legacy notes.json file.
        if isinstance(data, list):
            return {
                "folders": [],
                "notes": [
                    {
                        **note,
                        "folder_id": note.get("folder_id")
                    }
                    for note in data
                    if isinstance(note, dict)
                ],
            }

        if not isinstance(data, dict):
            return {
                "folders": [],
                "notes": [],
            }

        folders = data.get("folders", [])
        notes = data.get("notes", [])

        if not isinstance(folders, list):
            folders = []

        if not isinstance(notes, list):
            notes = []

        return {
            "folders": folders,
            "notes": notes,
        }

    except Exception:
        return {
            "folders": [],
            "notes": [],
        }


def save_notes_data(data):
    NOTES_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    NOTES_FILE.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def load_notes():
    return load_notes_data()["notes"]


def save_notes(notes):
    data = load_notes_data()
    data["notes"] = notes
    save_notes_data(data)


def folder_exists(data, folder_id):
    if folder_id is None:
        return True

    return any(
        folder.get("id") == folder_id
        for folder in data["folders"]
    )


def folder_is_descendant(data, folder_id, candidate_parent_id):
    current = candidate_parent_id
    seen = set()

    while current:
        if current == folder_id:
            return True

        if current in seen:
            return True

        seen.add(current)

        parent = next(
            (
                folder
                for folder in data["folders"]
                if folder.get("id") == current
            ),
            None,
        )

        if not parent:
            return False

        current = parent.get("parent_id")

    return False


@app.get("/api/notes")
def get_notes():
    with NOTES_LOCK:
        data = load_notes_data()

    data["folders"].sort(
        key=lambda item: item.get("name", "").lower()
    )

    data["notes"].sort(
        key=lambda item: item.get("name", "").lower()
    )

    return data


@app.post("/api/notes")
def create_note(request: NoteRequest):
    name = request.name.strip()
    content = request.content.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Name der Notiz fehlt",
        )

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Inhalt der Notiz fehlt",
        )

    with NOTES_LOCK:
        data = load_notes_data()

        if not folder_exists(data, request.folder_id):
            raise HTTPException(
                status_code=400,
                detail="Ordner nicht gefunden",
            )

        note = {
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "content": content,
            "folder_id": request.folder_id,
            "created_at": time.time(),
            "updated_at": time.time(),
        }

        data["notes"].append(note)
        save_notes_data(data)

    return {
        "ok": True,
        "note": note,
    }


@app.put("/api/notes/{note_id}")
def update_note(note_id: str, request: NoteRequest):
    name = request.name.strip()
    content = request.content.strip()

    if not name or not content:
        raise HTTPException(
            status_code=400,
            detail="Name und Inhalt dürfen nicht leer sein",
        )

    with NOTES_LOCK:
        data = load_notes_data()

        if not folder_exists(data, request.folder_id):
            raise HTTPException(
                status_code=400,
                detail="Ordner nicht gefunden",
            )

        for note in data["notes"]:
            if note.get("id") == note_id:
                note["name"] = name
                note["content"] = content
                note["folder_id"] = request.folder_id
                note["updated_at"] = time.time()

                save_notes_data(data)

                return {
                    "ok": True,
                    "note": note,
                }

    raise HTTPException(
        status_code=404,
        detail="Notiz nicht gefunden",
    )


@app.patch("/api/notes/{note_id}/folder")
def move_note(note_id: str, request: NoteMoveRequest):
    with NOTES_LOCK:
        data = load_notes_data()

        if not folder_exists(data, request.folder_id):
            raise HTTPException(
                status_code=400,
                detail="Ordner nicht gefunden",
            )

        for note in data["notes"]:
            if note.get("id") == note_id:
                note["folder_id"] = request.folder_id
                note["updated_at"] = time.time()

                save_notes_data(data)

                return {
                    "ok": True,
                    "note": note,
                }

    raise HTTPException(
        status_code=404,
        detail="Notiz nicht gefunden",
    )


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: str):
    with NOTES_LOCK:
        data = load_notes_data()

        new_notes = [
            note
            for note in data["notes"]
            if note.get("id") != note_id
        ]

        if len(new_notes) == len(data["notes"]):
            raise HTTPException(
                status_code=404,
                detail="Notiz nicht gefunden",
            )

        data["notes"] = new_notes
        save_notes_data(data)

    return {
        "ok": True,
    }


@app.post("/api/note-folders")
def create_note_folder(request: NoteFolderRequest):
    name = request.name.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Ordnername fehlt",
        )

    with NOTES_LOCK:
        data = load_notes_data()

        if not folder_exists(data, request.parent_id):
            raise HTTPException(
                status_code=400,
                detail="Übergeordneter Ordner nicht gefunden",
            )

        folder = {
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "parent_id": request.parent_id,
            "collapsed": False,
            "created_at": time.time(),
            "updated_at": time.time(),
        }

        data["folders"].append(folder)
        save_notes_data(data)

    return {
        "ok": True,
        "folder": folder,
    }


@app.patch("/api/note-folders/{folder_id}")
def update_note_folder(
    folder_id: str,
    request: NoteFolderUpdateRequest,
):
    with NOTES_LOCK:
        data = load_notes_data()

        folder = next(
            (
                item
                for item in data["folders"]
                if item.get("id") == folder_id
            ),
            None,
        )

        if not folder:
            raise HTTPException(
                status_code=404,
                detail="Ordner nicht gefunden",
            )

        if request.name is not None:
            name = request.name.strip()

            if not name:
                raise HTTPException(
                    status_code=400,
                    detail="Ordnername fehlt",
                )

            folder["name"] = name

        # model_fields_set matters here:
        # parent_id=null explicitly means "move to root."
        if "parent_id" in request.model_fields_set:
            parent_id = request.parent_id

            if parent_id == folder_id:
                raise HTTPException(
                    status_code=400,
                    detail="Ordner kann nicht sich selbst enthalten",
                )

            if not folder_exists(data, parent_id):
                raise HTTPException(
                    status_code=400,
                    detail="Zielordner nicht gefunden",
                )

            if folder_is_descendant(
                data,
                folder_id,
                parent_id,
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Ungültige Ordnerstruktur",
                )

            folder["parent_id"] = parent_id

        if request.collapsed is not None:
            folder["collapsed"] = request.collapsed

        folder["updated_at"] = time.time()
        save_notes_data(data)

    return {
        "ok": True,
        "folder": folder,
    }


@app.delete("/api/note-folders/{folder_id}")
def delete_note_folder(folder_id: str):
    with NOTES_LOCK:
        data = load_notes_data()

        folder = next(
            (
                item
                for item in data["folders"]
                if item.get("id") == folder_id
            ),
            None,
        )

        if not folder:
            raise HTTPException(
                status_code=404,
                detail="Ordner nicht gefunden",
            )

        parent_id = folder.get("parent_id")

        # Preserve notes.
        for note in data["notes"]:
            if note.get("folder_id") == folder_id:
                note["folder_id"] = parent_id

        # Move child folders up one level.
        for child in data["folders"]:
            if child.get("parent_id") == folder_id:
                child["parent_id"] = parent_id

        data["folders"] = [
            item
            for item in data["folders"]
            if item.get("id") != folder_id
        ]

        save_notes_data(data)

    return {
        "ok": True,
    }


# ============================================================
# Batch Transform
# ============================================================

BATCH_DIRECTORY = Path.home() / ".config/mlx-web/batch"
BATCH_JOBS_FILE = BATCH_DIRECTORY / "jobs.json"
BATCH_LOCK = threading.RLock()


def locked_batch_start(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with BATCH_LOCK:
            return function(*args, **kwargs)
    return wrapped


class BatchTransformRequest(BaseModel):
    input_path: str
    instruction: str
    file_type: str = "auto"
    chunk_tokens: int = 12000
    execution_mode: str = "automatic"
    trace_id: str | None = None


class ChatFileRouteRequest(BaseModel):
    input_path: str
    instruction: str = ""
    file_type: str = "auto"
    chunk_tokens: int = 12000
    attachment_id: str | None = None
    trace_id: str | None = None


class ChatActionRequest(BaseModel):
    prompt: str
    action: Literal["image_generate", "image_edit", "image_upscale"] | None = None
    file_context: dict | None = None
    active_artifact_id: str | None = None
    image_options: dict | None = None
    conversation_context: list[dict] | None = None
    instruction: str | None = None
    trace_id: str | None = None

class KnowledgeSourceRequest(BaseModel):
    path: str
    name: str | None = None
    force: bool = False

class KnowledgeSearchRequest(BaseModel):
    query: str
    scope: str | None = None


class UserProfileRequest(BaseModel):
    enabled: bool = True
    fields: dict = {}
    custom_fields: list[dict] = []


class CodeWorkspaceRequest(BaseModel):
    path: str
    name: str | None = None
    test_commands: list[list[str]] | None = None
class CodeReadRequest(BaseModel):
    workspace_id: str
    path: str
    start_line: int | None = None
    end_line: int | None = None
class CodeSearchRequest(BaseModel):
    workspace_id: str
    query: str
class CodePatchRequest(BaseModel):
    workspace_id: str
    instruction: str
    files: list[dict]
class CodeApprovalRequest(BaseModel): approved: bool = False


MAX_TOOL_STEPS = 8


FOLDER_PICKER_SCRIPT = """
set selectedFolder to choose folder with prompt "Coding-Workspace auswählen"
return POSIX path of selectedFolder
""".strip()


def pick_code_workspace_folder():
    """Open the native macOS folder picker without invoking a shell."""
    try:
        result = subprocess.run(
            ["osascript", "-e", FOLDER_PICKER_SCRIPT],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError("FOLDER_PICKER_UNAVAILABLE") from exc
    except OSError as exc:
        raise ValueError("FOLDER_PICKER_FAILED") from exc

    if result.returncode != 0:
        error = str(result.stderr or "")
        if "-128" in error or "cancel" in error.lower():
            return {"status": "cancelled"}
        raise ValueError("FOLDER_PICKER_FAILED")

    selected = str(result.stdout or "").strip()
    if not selected:
        raise ValueError("FOLDER_PICKER_EMPTY_RESULT")

    try:
        root = Path(selected).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError("WORKSPACE_INVALID_PATH") from exc

    if not root.exists() or not root.is_dir():
        raise ValueError("WORKSPACE_NOT_FOUND")
    if not os.access(root, os.R_OK | os.X_OK):
        raise ValueError("WORKSPACE_PERMISSION_DENIED")

    workspace = code_workspaces.add_workspace(
        str(root),
        activate=True,
    )
    return {
        "status": "selected",
        "path": str(root),
        "name": workspace["name"],
        "workspace_id": workspace["workspace_id"],
        "root_path": workspace["root_path"],
        "existing": workspace.get("existing", False),
    }


def code_http_error(exc):
    detail = str(exc)
    conflict_codes = {
        "PATCH_CONFLICT",
        "CREATE_CONFLICT",
        "REVERT_CONFLICT",
        "WORKSPACE_CHANGED",
        "PATCH_STATE_INVALID",
    }
    if any(
        detail == code or detail.startswith(code + ":")
        for code in conflict_codes
    ):
        return HTTPException(status_code=409, detail=detail)
    if detail.startswith(("PATCH_APPLY_FAILED:", "REVERT_FAILED:")):
        return HTTPException(status_code=500, detail=detail)
    if detail in {
        "WORKSPACE_NOT_FOUND",
        "WORKSPACE_ROOT_UNAVAILABLE",
        "FILE_NOT_FOUND",
        "PATCH_NOT_FOUND",
    }:
        return HTTPException(status_code=404, detail=detail)
    if detail in {
        "WORKSPACE_PERMISSION_DENIED",
        "PATH_OUTSIDE_WORKSPACE",
        "PATH_IGNORED",
        "SECRET_BLOCKED",
        "BINARY_FILE_BLOCKED",
    }:
        return HTTPException(status_code=403, detail=detail)
    return HTTPException(status_code=400, detail=detail)


CHAT_INLINE_FILE_MAX_BYTES = 100_000
FILE_SAMPLE_MAX_CHARS = 6_000


def load_batch_jobs():
    return batch_state.load_jobs(BATCH_JOBS_FILE)


def save_batch_jobs(jobs):
    batch_state.save_jobs(
        BATCH_DIRECTORY,
        BATCH_JOBS_FILE,
        jobs,
    )


@app.get("/api/batch")
def get_batch_jobs():
    with BATCH_LOCK:
        jobs = load_batch_jobs()

    items = list(jobs.values())

    items.sort(
        key=lambda item: item.get("created_at", 0),
        reverse=True,
    )

    return {
        "jobs": items
    }


@app.post('/api/batch/cleanup')
def cleanup_batch_history(request: HistoryCleanupRequest):
    statuses = history_statuses(request.scope)
    with BATCH_LOCK, BATCH_WORKERS_LOCK:
        # Strict parsing: never overwrite a corrupt/unreadable store with an empty one.
        try:
            jobs = json.loads(BATCH_JOBS_FILE.read_text(encoding='utf-8')) if BATCH_JOBS_FILE.exists() else {}
            if not isinstance(jobs, dict) or not all(isinstance(job, dict) for job in jobs.values()):
                raise ValueError('Ungültiger Job-Store')
            remaining = {key: job for key, job in jobs.items()
                         if job.get('status') not in statuses or key in BATCH_WORKERS}
            removed = len(jobs) - len(remaining)
            if removed:
                save_batch_jobs(remaining)
        except (OSError, ValueError) as exc:
            raise HTTPException(500, "Job-Historie konnte nicht sicher gelesen oder gespeichert werden.") from exc
    return {'ok': True, 'removed': removed, 'remaining': len(remaining)}


@app.post("/api/batch")
def create_batch_job(request: BatchTransformRequest):
    input_path = Path(
        request.input_path
    ).expanduser()

    instruction = request.instruction.strip()
    file_type = request.file_type.strip().lower()
    chunk_tokens = int(request.chunk_tokens)

    execution_mode = str(
        request.execution_mode or "automatic"
    ).strip().lower()

    if execution_mode not in {
        "automatic",
        "controlled",
    }:
        raise HTTPException(
            status_code=400,
            detail="Ungültiger Ausführungsmodus",
        )

    if not input_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Eingabedatei nicht gefunden",
        )

    if not input_path.is_file():
        raise HTTPException(
            status_code=400,
            detail="Eingabepfad ist keine Datei",
        )

    if not instruction:
        raise HTTPException(
            status_code=400,
            detail="Transformations-Anweisung fehlt",
        )

    if file_type not in {
        "auto",
        "text",
        "sql",
        "csv",
        "json",
    }:
        raise HTTPException(
            status_code=400,
            detail="Ungültiger Dateityp",
        )

    chunk_tokens = max(
        500,
        min(chunk_tokens, 20000),
    )

    job_id = uuid.uuid4().hex[:12]

    output_path = input_path.with_name(
        input_path.stem +
        ".transformed" +
        input_path.suffix
    )

    job = {
        "id": job_id,
        "trace_id": observability.ensure_trace_id(request.trace_id),
        "input_path": str(input_path),
        "output_path": str(output_path),
        "instruction": instruction,
        "file_type": file_type,
        "chunk_tokens": chunk_tokens,
        "execution_mode": execution_mode,
        "waiting_for_user": False,
        "status": "queued",
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "processed_chunks": 0,
        "total_chunks": None,
        "error": None,
        "llm_chunks": 0,
        "fast_only_chunks": 0,
        "skipped_llm_chunks": 0,
        "mlx_calls": 0,
    }

    with BATCH_LOCK:
        jobs = load_batch_jobs()
        jobs[job_id] = job
        save_batch_jobs(jobs)

    return {
        "ok": True,
        "job": job,
    }


@app.post("/api/chat/files/route")
def route_chat_file(request: ChatFileRouteRequest):
    """Route a chat attachment without putting the file into chat context."""
    instruction = request.instruction.strip()
    plan = classify_batch_instruction(instruction)
    transform_markers = (
        "anonymis", "entfern", "bereinig", "ersetz", "änder", "aender",
        "transformier", "schwärz", "schwaerz",
    )
    is_transform = bool(plan.get("operations")) or any(
        marker in instruction.lower() for marker in transform_markers
    )
    if not is_transform:
        value = instruction.lower()
        if any(word in value for word in ("fass", "zusammenfassung", "wichtigsten punkte")):
            operation = "summarize"
        elif any(word in value for word in ("auffällig", "auffaellig", "problem", "muster", "analys")):
            operation = "analyze"
        else:
            operation = "inspect"
        job = create_file_analysis_job(
            request.input_path, instruction, request.file_type,
            request.chunk_tokens, operation, request.attachment_id,
            request.trace_id,
        )
        start_file_analysis_job(job["id"])
        return {"intent": operation, "job": job}

    input_path = Path(
        request.input_path
    ).expanduser()

    file_size = (
        input_path.stat().st_size
        if input_path.exists()
        else 0
    )

    # Process large files in controlled mode:
    # pause after each fully saved chunk.
    execution_mode = (
        "controlled"
        if file_size >= 1024 * 1024
        else "automatic"
    )

    created = create_batch_job(BatchTransformRequest(
        input_path=request.input_path,
        instruction=instruction,
        file_type=request.file_type,
        chunk_tokens=request.chunk_tokens,
        execution_mode=execution_mode,
        trace_id=request.trace_id,
    ))

    job = created["job"]

    requires_start_choice = (
        execution_mode == "controlled"
    )

    # Continue to start small jobs immediately.
    # Large jobs remain queued until the user chooses how to proceed.
    if not requires_start_choice:
        start_batch_job(job["id"])

    return {
        "intent": "transform",
        "job": job,
        "plan": plan,
        "execution_mode": execution_mode,
        "requires_start_choice": requires_start_choice,
        "controlled_reason": (
            "large_file"
            if requires_start_choice
            else None
        ),
    }


MLX_CAPABILITY_MODEL = {
    "normal_chat": {
        "description": "Wissen erklären und allgemeine Fragen beantworten",
        "access": "keine lokale Untersuchung",
    },
    "diagnostic_agent": {
        "description": "Lokalen Mac, Prozesse, CPU, RAM, Speicherplatz, Systemstatus, Logs und Docker untersuchen",
        "access": "ausschließlich READ-ONLY",
    },
    "coding_agent": {
        "description": "Aktiven Coding-Workspace untersuchen und sichere CREATE/MODIFY/DELETE-Change-Sets vorbereiten",
        "access": "Lesen automatisch; Anwenden ausschließlich nach Approval",
    },
    "research_agent": {
        "description": "Mehrstufig im Web recherchieren, Quellen öffnen und vergleichen",
        "access": "READ/Research",
    },
    "orchestrator": {
        "description": "Komplexe mehrstufige Aufgaben über mehrere lokale Fähigkeiten hinweg planen und ausführen",
        "access": "READ automatisch; Änderungen nur über bestehende Approval-Workflows",
    },
    "knowledge_search": {
        "description": "Lokale Wissensbasis nach bereits indexiertem eigenem Wissen, Dokumentation und Fakten durchsuchen",
        "access": "READ/local knowledge",
    },
    "web_search": {
        "description": "Eine schnelle aktuelle Websuche durchführen",
        "access": "READ/Research",
    },
    "image_generate": {
        "description": "Ein Bild lokal mit dem konfigurierten Bildmodell erzeugen",
        "access": "spezialisierte Bild-Pipeline",
    },
    "image_edit": {
        "description": "Ein angehängtes oder aktives Bild lokal bearbeiten",
        "access": "spezialisierte Bild-Pipeline",
    },
    "image_upscale": {
        "description": "Ein angehängtes oder aktives Bild lokal mit Real-ESRGAN hochskalieren",
        "access": "spezialisierte Bild-Pipeline",
    },
    "vision": {
        "description": "Ein angehängtes oder aktives Bild mit einem Vision-Modell analysieren",
        "access": "Bildanalyse im normalen Chatpfad",
    },
    "file_analyze": {
        "description": "Eine angehängte Text-/Datendatei untersuchen oder zusammenfassen",
        "access": "bestehende sichere Datei-Pipeline",
    },
}
SEMANTIC_ROUTER_INTENTS = set(MLX_CAPABILITY_MODEL)
SEMANTIC_ROUTER_THRESHOLD = 0.75
SEMANTIC_ROUTER_AGENT_INTENTS = {
    "diagnostic_agent",
    "coding_agent",
    "research_agent",
    "orchestrator",
}


def capability_model_text():
    return "\n".join(
        f"- {intent}: {data['description']} ({data['access']})"
        for intent, data in MLX_CAPABILITY_MODEL.items()
    )


def _looks_like_disk_usage_request(prompt):
    value = re.sub(r"\s+", " ", str(prompt or "").strip().lower())
    storage = bool(re.search(
        r"\b(?:speicher|speicherplatz|speicherverbrauch|plattenspeicher|plattenplatz|"
        r"festplatte|ssd|disk\s+(?:space|usage)|storage\s+usage)\b",
        value,
    ))
    filesystem_subject = bool(re.search(
        r"\b(?:datei(?:en)?|ordner|files?|folders?|directories|mac|rechner|"
        r"computer|festplatte|ssd)\b",
        value,
    ))
    strong_storage_term = bool(re.search(
        r"\b(?:speicherplatz|speicherverbrauch|plattenspeicher|plattenplatz|"
        r"festplatte|ssd|disk\s+(?:space|usage)|storage\s+usage)\b",
        value,
    ))
    if "am meisten platz" in value and filesystem_subject:
        storage = True
    ranked_items = bool(re.search(
        r"\b(?:grö(?:ß|ss)t(?:e|en|er)?|largest|biggest)\b.*\b"
        r"(?:datei(?:en)?|ordner|files?|folders?|directories)\b",
        value,
    ))
    project_context = bool(re.search(
        r"\b(?:projekt|workspace|codebase|repository|repo)\b",
        value,
    ))
    process_memory = bool(re.search(
        r"\b(?:prozess(?:e)?|ram|arbeitsspeicher)\b",
        value,
    ))
    storage_action = bool(re.search(
        r"\b(?:prüf|pruef|analysier|untersuch|zeig|find|welch|was|warum|"
        r"beleg|verbrauch|brauch|voll|freigeben|inspect|analy[sz]|show|find|"
        r"what|why|full|consume|use)\w*\b",
        value,
    ))
    if process_memory and not ranked_items:
        return False
    return (
        (ranked_items and not project_context)
        or (
            storage
            and storage_action
            and (filesystem_subject or strong_storage_term)
        )
    )



_IMAGE_FILE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
    ".avif",
}


def _file_context_is_image(file_context):
    """Return True only for file contexts that actually represent images."""
    if not isinstance(file_context, dict):
        return False

    kind = str(
        file_context.get("kind") or ""
    ).strip().lower()

    if kind == "image":
        return True

    mime_type = str(
        file_context.get("mime_type")
        or file_context.get("mime")
        or ""
    ).strip().lower()

    if mime_type.startswith("image/"):
        return True

    candidate = str(
        file_context.get("stored_path")
        or file_context.get("path")
        or file_context.get("name")
        or file_context.get("filename")
        or ""
    ).strip().lower()

    if candidate:
        from pathlib import Path as _Path

        if _Path(candidate).suffix.lower() in _IMAGE_FILE_EXTENSIONS:
            return True

    return False


_IMAGE_EDIT_VERB_PATTERN = re.compile(
    r"\b(?:"
    r"bearbeit(?:e|en)?|"
    r"änder(?:e|n)?|aender(?:e|n)?|"
    r"veränder(?:e|n)?|veraender(?:e|n)?|"
    r"färb(?:e|en)?|faerb(?:e|en)?|"
    r"entfern(?:e|en)?|"
    r"lösch(?:e|en)?|loesch(?:e|en)?|"
    r"ersetz(?:e|en)?|"
    r"füg(?:e|en)?|fueg(?:e|en)?|"
    r"retuschier(?:e|en)?|"
    r"korrigier(?:e|en)?|"
    r"verbesser(?:e|n)?|"
    r"change|edit|modify|recolor|remove|replace|add|retouch|blur"
    r")\b",
    re.IGNORECASE,
)

_IMAGE_EDIT_MAKE_PATTERN = re.compile(
    r"\b(?:mach|mache|make)\b",
    re.IGNORECASE,
)

_IMAGE_EDIT_MODIFIER_PATTERN = re.compile(
    r"\b(?:"
    r"rot|blau|grün|gruen|gelb|schwarz|weiß|weiss|blond|"
    r"heller|dunkler|dunkel|hell|wärmer|waermer|kälter|kaelter|"
    r"jünger|juenger|älter|aelter|"
    r"unscharf|scharf|weg|"
    r"hintergrund|farbe|farben|person|objekt|gesicht|haare|"
    r"bart|kleidung|stil|"
    r"schwarzweiß|schwarz-weiss|schwarz-weiß|"
    r"größer|groesser|kleiner|entfernt|"
    r"red|blue|green|yellow|black|white|blonde?|"
    r"lighter|darker|dark|bright|younger|older|"
    r"blurry|blurred|sharp|"
    r"background|color|colour|object|face|hair|beard|"
    r"realistischer|"
    r"clothing|style|remove|removed|warmer|cooler|more realistic"
    r")\b",
    re.IGNORECASE,
)

_IMAGE_EDIT_FOLLOWUP_PATTERN = re.compile(
    r"^\s*"
    r"(?:(?:und\s+)?(?:jetzt|nun|noch|then|now)\b.*)?"
    r"(?:bitte\s+)?"
    r"(?:(?:mehr|etwas|ein\s+bisschen|more|a\s+bit)\s+)?"
    r"(?:"
    r"ganzkörper|ganzkoerper|full[ -]?body|"
    r"dunkler|heller|wärmer|waermer|kälter|kaelter|"
    r"realistischer|jünger|juenger|älter|aelter|"
    r"unscharf|schärfer|schaerfer|"
    r"weiter\s+(?:raus|weg)|näher|naeher|"
    r"länger|laenger|kürzer|kuerzer|"
    r"darker|lighter|warmer|cooler|more realistic|"
    r"younger|older|blurrier|sharper|"
    r"zoom(?:ed)?\s+out|zoom(?:ed)?\s+in|longer|shorter"
    r")\b",
    re.IGNORECASE,
)

_IMAGE_QUESTION_PATTERN = re.compile(
    r"^\s*(?:"
    r"was|wie|welche|welcher|welches|wer|wo|wann|warum|"
    r"ist|sind|hat|haben|"
    r"what|how|which|who|where|when|why|"
    r"is|are|does|do|has|have"
    r")\b",
    re.IGNORECASE,
)

_IMAGE_CREATION_VERB_PATTERN = re.compile(
    r"\b(?:"
    r"erstelle|erstellen|generiere|generieren|"
    r"erzeuge|erzeugen|zeichne|zeichnen|mach|mache|"
    r"create|generate|draw|make"
    r")\b",
    re.IGNORECASE,
)

_IMAGE_NOUN_PATTERN = re.compile(
    r"\b(?:bild|foto|illustration|image|photo|picture)\b",
    re.IGNORECASE,
)

_IMAGE_NOUN_OF_PATTERN = re.compile(
    r"\b(?:bild|foto|illustration|image|photo|picture)\s+(?:von|of)\b",
    re.IGNORECASE,
)


def _deterministic_chat_action(prompt, file_context=None, conversation_context=None):
    """Lightweight intent router: never receives a file body."""
    value = str(prompt or "").strip().lower()
    try:
        active_code_workspace = code_workspaces.active_workspace() is not None
    except ValueError:
        active_code_workspace = False

    # ----------------------------------------------------
    # Automatic orchestrator
    # ----------------------------------------------------
    # Takes precedence over individual specialist agents when the
    # prompt clearly requires several capabilities.
    explicit_local_project_reference = any(
        marker in value
        for marker in (
            "mein projekt",
            "meinem projekt",
            "mein nobbymlx",
            "meinem nobbymlx",
            "mein code",
            "meinem code",
            "lokaler code",
            "lokalen code",
            "lokalem code",
        )
    )

    external_research_context = any(
        marker in value
        for marker in (
            "recherch",
            "internet",
            "im web",
            "online",
            "aktuell",
            "aktuelle",
            "news",
        )
    )

    cross_capability_intent = any(
        marker in value
        for marker in (
            "vergleiche",
            "vergleich",
            "kombiniere",
            "führe zusammen",
            "fuehre zusammen",
            "anschließend",
            "anschliessend",
            "danach",
            "mit meinem lokalen code",
            "mit meinem code",
            "mit meinem projekt",
        )
    )

    local_project_context = (
        explicit_local_project_reference
        or (
            active_code_workspace
            and any(
                marker in value
                for marker in (
                    "projekt",
                    "workspace",
                    "codebase",
                    "quellcode",
                    "backend",
                    "frontend",
                )
            )
        )
    )

    if (
        local_project_context
        and external_research_context
        and cross_capability_intent
    ):
        return "orchestrator"
    if _looks_like_disk_usage_request(value):
        return "diagnostic_agent"
    if (
        file_context
        and _file_context_is_image(file_context)
        and _looks_like_image_edit_request(value)
    ):
        return "image_edit"

    if _looks_like_image_generation_request(value):
        return "image_generate"
    if "indexiere" in value:
        return "knowledge_add"
    if any(word in value for word in ("wie viele dateien", "knowledge status", "status der wissensbasis")):
        return "knowledge_status"
    if any(
        marker in value
        for marker in (
            "wissensbasis",
            "knowledge base",
            "knowledge-base",
            "lokales wissen",
            "lokale wissensbasis",
            "suche in meiner wissensbasis",
            "suche in der wissensbasis",
        )
    ):
        return "knowledge_search"
    if file_context and any(word in value for word in ("anonymis", "entfern", "bereinig", "ersetz", "änder", "aender", "transformier")):
        return "file_transform"
    if file_context and any(word in value for word in ("fass", "zusammenfass")):
        return "file_summarize"
    if file_context and any(word in value for word in ("analys", "auffällig", "auffaellig", "problem", "muster")):
        return "file_analyze"
    if file_context and any(word in value for word in ("pii audit", "personenbezogene daten", "noch daten drin", "nochmal prüfen", "nochmal pruefen")):
        return "pii_audit"
    if file_context and any(word in value for word in ("prüf", "pruef", "struktur", "felder", "datensätz", "datensaetz", "zeitraum", "was ist")):
        return "file_inspect"
    model_list_request = any(
        phrase in value
        for phrase in (
            "welches modell läuft",
            "welches modell laeuft",
            "welches modell ist aktiv",
            "welches modell ist geladen",
            "welche modelle sind installiert",
            "welche modelle installiert",
            "welche modelle sind verfügbar",
            "welche modelle sind verfuegbar",
            "welche modelle sind vorhanden",
            "welche modelle sind geladen",
            "zeig mir die modelle",
            "zeige mir die modelle",
            "liste die modelle",
            "modellliste",
            "modellstatus",
            "aktives modell",
            "aktive modell",
        )
    )

    if model_list_request:
        return "model_list"

    if any(word in value for word in ("thinking an", "thinking ein", "thinking on")):
        return "thinking_on"
    if any(word in value for word in ("thinking aus", "thinking off")):
        return "thinking_off"
    if any(word in value for word in ("letzten fehler", "logs", "protokoll", "log anzeigen")):
        return "logs_query"
    batch_status_request = any(
        word in value
        for word in (
            "was läuft gerade",
            "welche jobs",
            "welche aufgaben",
            "batch status",
            "batch-status",
            "datei-jobs",
        )
    )

    code_context = any(
        word in value
        for word in (
            "code",
            "quellcode",
            "programm",
            "funktion",
            "klasse",
            "projekt",
            "debug",
        )
    )

    if batch_status_request and not code_context:
        return "batch_status"

    programming_knowledge_question = bool(re.match(
        r"^(?:wie\s+(?:funktioniert|kann\s+ich|baut\s+man|erstell(?:e|t)?\s+(?:man|ich))|"
        r"was\s+(?:ist|bedeutet)|erkläre|erklaere)\b",
        value,
    ))
    conversation_text = " ".join(
        str(entry.get("content") or "").lower()
        for entry in (conversation_context or [])[-8:]
        if isinstance(entry, dict)
    )
    coding_conversation = any(
        marker in conversation_text
        for marker in (
            "agent-auftrag",
            "coding-agent",
            "workspace",
            "patch",
            "änderung erfolgreich angewendet",
            "datei erstellt",
            "datei geändert",
            "datei gelöscht",
        )
    )

    delete_intent = any(
        marker in value
        for marker in (
            "lösche",
            "loesche",
            "lösch ",
            "loesch ",
            "entferne die datei",
            "entferne datei",
            "delete ",
            "remove ",
            "kann weg",
        )
    )
    if (
        active_code_workspace
        and delete_intent
        and not programming_knowledge_question
    ):
        return "coding_agent"

    # Explicit code and file changes take precedence.
    coding_change_targets = (
        "code",
        "quellcode",
        "projekt",
        "workspace",
        "python",
        "javascript",
        "typescript",
        "php",
        "backend",
        "frontend",
        "funktion",
        "klasse",
        "datei",
        ".py",
        ".js",
        ".ts",
        ".php",
        ".html",
        ".css",
        ".json",
        ".txt",
        "webseite",
        "web-app",
        "webapp",
        "rest-api",
        "rest api",
        "api",
        "dark mode",
        "dark-mode",
        "admin-oberfläche",
        "admin oberfläche",
        "benutzerverwaltung",
        "datenbank",
        "pdo",
        "responsive",
        "newsletter",
        "modul",
        *(('login', 'navigation', 'readme', 'ordner', 'hier', 'header', 'button', 'farbe') if active_code_workspace else ()),
    )

    coding_change_intents = (
        "ändere",
        "aendere",
        "modifiziere",
        "bearbeite",
        "implementiere",
        "implementier",
        "repariere",
        "reparier",
        "behebe",
        "fixe",
        "ersetze",
        "entferne",
        "füge ",
        "fuege ",
        "ergänze",
        "ergaenze",
        "erstelle",
        "erstell",
        "erzeuge",
        "lege ",
        "leg ",
        "schreibe",
        "schreib ",
        "baue",
        "bau ",
        "refaktoriere",
        "refaktorier",
        "überarbeite",
        "ueberarbeite",
        "mach ",
    )

    if (
        not programming_knowledge_question
        and
        any(x in value for x in coding_change_targets)
        and any(x in value for x in coding_change_intents)
    ):
        return "coding_agent"

    if (
        active_code_workspace
        and coding_conversation
        and not programming_knowledge_question
        and any(x in value for x in coding_change_intents)
    ):
        return "coding_agent"

        # The word "status" inside file or code content must not
        # accidentally trigger a system status request.
    system_status_request = (
        any(
            x in value
            for x in (
                "agent erreichbar",
                "systemstatus",
                "system status",
                "server status",
                "server-status",
                "mlx status",
                "mlx-status",
                "agent status",
                "agent-status",
            )
        )
        or ("ram" in value and "modell" in value)
        or value.strip() == "status"
    )

        # A simple status request remains a fast direct tool.
        # A genuine diagnostic or analysis request must enter the
        # diagnostic agent loop so it can coordinate several read-only
        # system observations.
    diagnostic_analysis_request = (
        _looks_like_local_diagnostic(
            prompt,
            conversation_context,
        )
        or (
            any(
                marker in value
                for marker in (
                    "diagnostic-spezialagent",
                    "diagnostic spezialagent",
                    "diagnostic-agent",
                    "diagnostic agent",
                    "diagnostic_agent",
                )
            )
            and any(
                marker in value
                for marker in (
                    "prüf",
                    "pruef",
                    "untersuch",
                    "analys",
                    "prozess",
                    "dienste",
                    "dienst",
                    "systemstatus",
                    "system status",
                )
            )
        )
    )

    if system_status_request and not diagnostic_analysis_request:
        return "system_status"
    model_match = re.search(
        r"(?:"
        r"wechsle\s+auf\s+([a-z0-9._-]+)"
        r"|"
        r"(?:wechsle|starte)\s+(?:das\s+)?modell\s+([a-z0-9._-]+)"
        r")",
        value,
    )

    if model_match:
        model_alias = next(
            (
                group
                for group in model_match.groups()
                if group
            ),
            None,
        )

        if model_alias and model_alias not in {
            "das",
            "den",
            "die",
            "neu",
        }:
            return "model_switch"
    if any(word in value for word in ("modell neu starten", "mlx neu starten", "server neu starten")):
        return "model_restart"
    # ----------------------------------------------------
    # Live-Websuche
    # ----------------------------------------------------
    explicit_web_search = any(
        marker in value
        for marker in (
            "suche im web",
            "suche online",
            "suche im internet",
            "websuche",
            "web search",
            "im internet suchen",
            "im internet nachsehen",
            "online nachsehen",
            "durchsuche das internet",
            "durchsuch das internet",
            "durchsuche das web",
            "durchsuch das web",
            "recherchiere im internet",
            "recherchiere online",
            "recherchiere im web",
            "recherchier im internet",
            "recherchier online",
            "recherchier im web",
            "google das",
            "google nach",
        )
    )

    freshness_markers = (
        "aktuell",
        "aktuelle",
        "aktuellen",
        "heute",
        "gerade",
        "neueste",
        "neuesten",
        "neues",
        "neuigkeiten",
        "was ist neu",
        "was gibt es neues",
        "was gibts neues",
        "letzte meldung",
        "letzten meldungen",
        "letzte entwicklung",
        "letzten entwicklungen",
        "news",
        "nachrichten",
        "stand heute",
        "derzeit",
        "momentan",
    )

    likely_current_question = any(
        marker in value
        for marker in freshness_markers
    )

    # ----------------------------------------------------
    # Automatic research agent
    # ----------------------------------------------------
    # Use only for clearly multi-step research.
    # Simple current-information questions stay on the fast web_search path.

    research_markers = (
        "mehrere quellen",
        "mindestens zwei quellen",
        "mindestens 2 quellen",
        "mindestens drei quellen",
        "mindestens 3 quellen",
        "öffne anschließend",
        "oeffne anschliessend",
        "öffne danach",
        "oeffne danach",
        "vergleiche die quellen",
        "vergleiche quellen",
        "prüfe mehrere quellen",
        "pruefe mehrere quellen",
        "recherchiere ausführlich",
        "recherchiere ausfuehrlich",
        "gründlich recherch",
        "gruendlich recherch",
        "tiefe recherche",
        "deep research",
    )

    multi_step_research = any(
        marker in value
        for marker in research_markers
    )

    if re.search(r"\brecherchier(?:e|en)?\b", value) and likely_current_question:
        return "research_agent"

    if (
        multi_step_research
        and (
            explicit_web_search
            or likely_current_question
            or "recherch" in value
        )
    ):
        return "research_agent"

    # ----------------------------------------------------
    # Automatische technische Diagnose
    # ----------------------------------------------------

    diagnostic_targets = (
        "docker",
        "container",
        "open webui",
        "open-webui",
        "mlx-server",
        "mlx server",
        "mlx agent",
        "searxng",
        "server",
        "dienst",
        "service",
        "prozess",
        "ram",
        "speicher",
        "port",
        "localhost",
    )

    diagnostic_intents = (
        "untersuche",
        "diagnostiz",
        "finde den fehler",
        "find den fehler",
        "warum läuft",
        "warum laeuft",
        "warum funktioniert",
        "warum antwortet",
        "nicht erreichbar",
        "reagiert nicht",
        "funktioniert nicht",
        "läuft nicht",
        "laeuft nicht",
        "prüfe warum",
        "pruefe warum",
        "prüf warum",
        "pruef warum",
    )

    diagnostic_agent = (
        any(marker in value for marker in diagnostic_targets)
        and
        any(marker in value for marker in diagnostic_intents)
    )

    if diagnostic_agent:
        return "diagnostic_agent"

    # ----------------------------------------------------
    # Automatische Code-Untersuchung
    # ----------------------------------------------------

    coding_targets = (
        "code",
        "projekt",
        "workspace",
        "python",
        "javascript",
        "typescript",
        "php",
        "backend",
        "frontend",
        "funktion",
        "klasse",
        "datei",
        *(('login', 'navigation', 'readme', 'ordner') if active_code_workspace else ()),
    )

    coding_intents = (
        "untersuche",
        "analysiere",
        "analysier",
        "finde den fehler",
        "find den fehler",
        "suche den fehler",
        "such den fehler",
        "debug",
        "warum funktioniert",
        "warum läuft",
        "warum laeuft",
        "prüfe den code",
        "pruefe den code",
        "prüf den code",
        "pruef den code",
        "prüfe alle",
        "pruefe alle",
    )

    coding_agent = (
        any(marker in value for marker in coding_targets)
        and
        any(marker in value for marker in coding_intents)
    )

    if coding_agent:
        return "coding_agent"

    if programming_knowledge_question:
        return "normal_chat"

    if explicit_web_search:
        return "web_search"

    # ----------------------------------------------------
    # Automatic current-information search
    # ----------------------------------------------------
    # Freshness terms such as "today" are not sufficient on their own:
    # "Today I had a bad day" must not trigger a web search.
    # When paired with a clear request for information, current questions
    # are answered directly through web_search.
    live_information_request = likely_current_question and (
        any(
            marker in value
            for marker in (
                "news",
                "nachrichten",
                "neuigkeiten",
                "letzte meldung",
                "letzten meldungen",
                "letzte entwicklung",
                "letzten entwicklungen",
                "stand heute",
                "was ist neu",
                "was gibt es neues",
                "was gibts neues",
            )
        )
        or bool(
            re.search(
                r"^(?:bitte\s+)?(?:"
                r"fass(?:e)?|"
                r"was|wie|wer|wo|wann|welch\w*|"
                r"gib|zeig|nenne"
                r")\b",
                value,
            )
        )
    )

    if (
        live_information_request
        and not _looks_like_local_diagnostic(
            prompt,
            conversation_context,
        )
    ):
        return "web_search"

    return None

def _direct_chat_action(prompt, file_context=None, conversation_context=None):
    """Return only unambiguous direct actions that may bypass the LLM router.

    The legacy deterministic router also recognizes agent-like natural-language
    requests.  Those candidates are deliberately ignored here so that ordinary
    prose is classified semantically before an agent loop can start.
    """
    candidate = _deterministic_chat_action(
        prompt,
        file_context,
        conversation_context,
    )
    if candidate == "orchestrator":
        return candidate

    if (
        candidate == "web_search"
        and _looks_like_creative_chat_request(prompt)
        and not _looks_like_external_information_request(prompt)
    ):
        # Creative writing, roleplay and fictional scenarios do not
        # need external information merely because they mention
        # locations, events, people, time or environmental details.
        #
        # Let the semantic router decide instead of forcing web search.
        return None

    if (
        candidate == "web_search"
        and _looks_like_cross_capability_request(
            prompt,
            conversation_context,
        )
    ):
        # Web + local-project tasks need semantic arbitration.
        return None

    # Agent-like natural-language intents remain semantic so an LLM
    # classification plus the existing safety gate can validate them.
    #
    # A deterministic normal_chat result is different: it represents a
    # high-confidence knowledge/explanation question that explicitly does
    # not require tools. Let it bypass the semantic router so ordinary
    # programming knowledge cannot be misrouted to knowledge_search.
    if candidate in SEMANTIC_ROUTER_AGENT_INTENTS:
        return None

    return candidate

def _router_context_text(conversation_context):
    entries=[]
    for entry in (conversation_context or [])[-6:]:
        if not isinstance(entry, dict):
            continue
        role=str(entry.get("role") or "").strip().lower()
        content=str(entry.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            entries.append({"role": role, "content": content[:1200]})
    return json.dumps(entries, ensure_ascii=False)


def semantic_intent_classifier(
    prompt,
    file_context=None,
    conversation_context=None,
):
    try:
        active_workspace=code_workspaces.active_workspace(validate=False)
    except ValueError:
        active_workspace=None
    system_prompt=f"""
Du bist ausschließlich der semantische Intent-Classifier von MLX nobby.
Du beantwortest die Nutzerfrage NICHT. Du entscheidest nur, welcher bereits
vorhandene lokale Pfad die Anfrage bearbeiten soll.

MLX nobby ist kein generischer Cloud-Chatbot. Es besitzt diese Fähigkeiten:
{capability_model_text()}

Entscheide nach der Absicht, nicht nach einzelnen Schlüsselwörtern:
- Eine Bitte, den eigenen Mac jetzt zu prüfen, gehört zum diagnostic_agent.
- Eine Analyse großer Dateien, Ordner oder des lokalen Speicherplatzes gehört
  zum diagnostic_agent.
- Eine Erklärung, wie der Nutzer selbst etwas prüfen kann, gehört zu normal_chat.
- Eine gewünschte Änderung im eigenen Projekt gehört zum coding_agent.
- Das Prüfen, Bewerten oder Verbessern einer konkreten Datei im aktiven
  Coding-Workspace gehört ebenfalls zum coding_agent, auch wenn noch keine
  konkrete Änderung verlangt wird. Beispiele: "Schau dir index.html an",
  "Kann man login.php besser machen?" oder "Prüfe diese CSS-Datei".
- Eine Wissensfrage über Programmierung gehört zu normal_chat.
- knowledge_search ist für Fragen über Informationen gedacht, die in der lokalen
  Wissensbasis von MLX nobby indexiert sein können.
- Fragen über die eigene MLX nobby-Architektur, lokale Dokumentation,
  Konfiguration oder zuvor indexiertes Wissen gehören zu knowledge_search.
- Fragen nach lokalen MLX nobby-Diensten, deren Ports, verwendeten Modellen,
  Router, Embeddings, Speech- oder Image-Diensten gehören zu knowledge_search,
  solange keine aktuelle Systemdiagnose oder Statusprüfung verlangt wird.
- Verwende knowledge_search NICHT für allgemeines Weltwissen.
- Verwende web_search statt knowledge_search, wenn ausdrücklich aktuelle oder
  externe Informationen aus dem Internet benötigt werden.
- Medizinische, persönliche oder zwischenmenschliche Fragen gehören zu
  normal_chat. Das Wort "diagnostiziert" ist keine technische Systemdiagnose.
- Zeichenfolgen innerhalb längerer Wörter sind keine Absichtssignale. Zum
  Beispiel sind "api" in "Therapie" und "erstell" in "Reiterstellung" keine
  Coding-Anfrage.
- Eine aktuelle, mehrstufige Recherche mit Vergleich gehört zum research_agent;
  eine einzelne schnelle Onlinesuche zu web_search.
- orchestrator ist für komplexe Aufgaben gedacht, die mehrere unterschiedliche
  Fähigkeiten kombinieren müssen, z. B. Webrecherche + lokaler Code,
  Wissensbasis + Web oder Systemdiagnose + Codeanalyse.
- Verwende orchestrator NICHT für Aufgaben, die vollständig mit genau einem
  spezialisierten Agenten erledigt werden können.
- Setze requires_tools nur dann auf true, wenn die Anfrage tatsächlich lokale
  Werkzeuge, den Coding-Workspace, eine Websuche oder eine Spezialpipeline
  benötigt. Allgemeine Beratung und Wissen benötigen keine Tools.
- Routing allein darf niemals eine mutierende Aktion ausführen.

Antworte ausschließlich mit genau einem gültigen JSON-Objekt.
Kein Markdown, kein zusätzlicher Text vor oder nach dem JSON.
"reason" muss sehr kurz sein: maximal 12 Wörter.

{{"intent":"...","confidence":0.0,"requires_tools":false,"reason":"maximal 12 Wörter"}}
Erlaubte Intents: {', '.join(sorted(SEMANTIC_ROUTER_INTENTS))}
""".strip()
    user_payload={
        "prompt": str(prompt or "")[:4000],
        "has_file_context": bool(file_context),
        "active_coding_workspace": bool(active_workspace),
        "conversation_context": json.loads(
            _router_context_text(conversation_context)
        ),
    }
    response=router_llm(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        max_tokens=320,
        temperature=0.0,
    )
    parsed=parse_agent_json(response)
    intent=str(parsed.get("intent") or "").strip().lower()
    aliases={
        "image_generation": "image_generate",
        "file_analysis": "file_analyze",
    }
    intent=aliases.get(intent, intent)
    try:
        confidence=max(0.0, min(1.0, float(parsed.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence=0.0
    requires_tools=parsed.get("requires_tools")
    if not isinstance(requires_tools, bool):
        # Backward-compatible default for models/tests still returning the
        # previous schema. The classifier prompt always requests the field.
        requires_tools=intent != "normal_chat"
    return {
        "intent": intent,
        "confidence": confidence,
        "requires_tools": requires_tools,
        "reason": str(parsed.get("reason") or "").strip()[:500],
    }


def _looks_like_local_diagnostic(prompt, conversation_context=None):
    value=str(prompt or "").strip().lower()
    if re.match(
        r"^(?:wie kann ich|wie funktioniert|was ist|was bedeutet|erkläre|erklaere)\b",
        value,
    ):
        return False
    local_subject=bool(re.search(
        r"\b(?:mein(?:em|en|er)?\s+(?:mac|rechner|system)|mac|rechner|system|"
        r"cpu|ram|speicher|prozess(?:e)?|app(?:s)?|docker|container|leistung|"
        r"auslastung|systemverbrauch)\b",
        value,
    ))
    inspection=bool(re.search(
        r"\b(?:prüf|pruef|schau|untersuch|analysier|find|zeig|welch|was|warum|"
        r"frisst|zieht|belastet|langsam|amok)\w*\b",
        value,
    ))
    context_text=_router_context_text(conversation_context).lower()
    diagnostic_followup=bool(conversation_context) and any(
        marker in context_text
        for marker in (
            "diagnostic_agent",
            "system wird untersucht",
            "systemstatus",
            "cpu",
            "ram",
            "prozess",
            "docker",
            "mac gerade so langsam",
        )
    )
    followup_reference=bool(re.search(
        r"\b(?:davon|dabei|und was|welcher davon|was davon|ist es)\b",
        value,
    ))
    return (local_subject and inspection) or (
        diagnostic_followup and followup_reference
    )

def _looks_like_coding_action(prompt, conversation_context=None):
    """Conservative fallback used only when semantic classification fails."""
    value=str(prompt or "").strip().lower()
    try:
        active_workspace=code_workspaces.active_workspace() is not None
    except ValueError:
        active_workspace=False
    if re.match(
        r"^(?:wie\s+(?:funktioniert|kann\s+ich|baut\s+man|"
        r"erstell(?:e|t)?\s+(?:man|ich))|"
        r"was\s+(?:ist|bedeutet)|erkläre|erklaere)\b",
        value,
    ):
        return False

    explicit_target=bool(re.search(
        r"(?:\b(?:code|quellcode|projekt|workspace|python|javascript|typescript|"
        r"php|backend|frontend|funktion|klasse|datei(?:en)?|webseite|web-app|webapp|"
        r"rest-api|api|datenbank|pdo|newsletter|modul)\b|"
        r"\.(?:py|js|ts|php|html|css|json|txt)\b|"
        r"\bdark[ -]mode\b|\badmin[ -]oberfläche\b|"
        r"\bbenutzerverwaltung\b|\bresponsive(?:s|n|m|r)?\b)",
        value,
    ))
    if active_workspace:
        explicit_target=explicit_target or bool(re.search(
            r"\b(?:login|navigation|readme|hier|header|button|farbe)\b",
            value,
        ))
    change_intent=bool(re.search(
        r"\b(?:ändere|aendere|modifiziere|bearbeite|implementiere|implementier|"
        r"repariere|reparier|behebe|fixe|ersetze|entferne|füge|fuege|ergänze|"
        r"ergaenze|erstelle|erstell|erstellen|erzeuge|lege|schreibe|baue|bau|"
        r"refaktoriere|refaktorier|überarbeite|ueberarbeite|lösche|loesche|"
        r"remove|delete|analysiere|analysier|suche|such|prüfe|pruefe|"
        r"bewerte|bewert|verbessere|verbesser|mach|mache)\b",
        value,
    )) or bool(
        re.search(r"\bschau(?:e)?\s+(?:dir\s+)?(?:das|die|den|diese[nrsm]?|.+?)\s+an\b", value)
    ) or bool(
        re.search(r"\bkann\s+man\b.*\bbesser\s+machen\b", value)
    ) or bool(re.search(r"\bstell(?:e)?\b.*\bum\b", value)) or "kann weg" in value

    context_text=_router_context_text(conversation_context).lower()
    coding_followup=bool(conversation_context) and any(
        marker in context_text
        for marker in (
            "coding_agent",
            "coding-agent",
            "workspace",
            "patch",
            "änderung erfolgreich angewendet",
            "datei erstellt",
            "datei geändert",
        )
    )
    followup_change=bool(re.search(
        r"\b(?:mach|mache|ändere|aendere|entferne|lösche|loesche|"
        r"füge|fuege|einfügen|einfuegen|ergänze|ergaenze|erweitere|"
        r"baue|bau|implementiere|implementier|ändere|aendere)\b",
        value,
    ))
    return (explicit_target and change_intent) or (
        coding_followup and followup_change
    )

def _looks_like_creative_chat_request(prompt):
    """Recognize creative conversation that should normally stay in chat."""
    value = str(prompt or "").strip().lower()

    return bool(re.search(
        r"\b(?:"
        r"rollenspiel|roleplay|role-play|"
        r"spielleiter|game master|gm|"
        r"geschichte|story|szene|szenario|"
        r"charakter|dialog|erzähle|erzaehle|"
        r"spiele|simuliere|simulation|"
        r"in medias res"
        r")\b",
        value,
        re.IGNORECASE,
    ))

def _looks_like_external_information_request(prompt):
    """
    Return True only when the user actually needs information
    from outside the conversation/model context.

    Creative prompts mentioning places, time, events, people,
    weather-like scene elements, etc. must not be treated as
    web requests merely because those words occur in the prompt.
    """
    value = str(prompt or "").strip().lower()

    if not value:
        return False

    explicit_search = bool(re.search(
        r"(?:^|[\s,.;:!?()])(?:"
        r"suche|such|suchst|sucht|"
        r"recherchiere|recherchier|recherchiert|"
        r"finde|find|"
        r"schau\s+(?:im\s+)?web|"
        r"schau\s+online|"
        r"such\s+(?:im\s+)?internet|"
        r"look\s+up|search|research"
        r")(?:$|[\s,.;:!?()])",
        value,
        re.IGNORECASE,
    ))

    explicit_source_request = bool(re.search(
        r"(?:^|[\s,.;:!?()])(?:"
        r"quelle|quellen|"
        r"webseite|webseiten|"
        r"website|websites|"
        r"onlinequelle|onlinequellen|"
        r"link|links"
        r")(?:$|[\s,.;:!?()])",
        value,
        re.IGNORECASE,
    ))

    current_external_data = bool(re.search(
        r"(?:"
        r"\bwetter\s+(?:heute|morgen|aktuell)|"
        r"\b(?:aktueller|aktuellen|aktuelles|aktuelle)\s+"
        r"(?:kurs|preis|stand|version|news|nachrichten)|"
        r"\b(?:bitcoin|btc|ethereum|eth|aktien?|börse|boerse)\s+"
        r"(?:kurs|preis|aktuell)|"
        r"\b(?:neueste|neuesten|letzte|letzten)\s+"
        r"(?:news|nachrichten|meldungen|version)"
        r")",
        value,
        re.IGNORECASE,
    ))

    return (
        explicit_search
        or explicit_source_request
        or current_external_data
    )



def _looks_like_research_request(prompt):
    """Return True for clearly multi-source/current research requests."""
    value = str(prompt or "").strip().lower()

    explicit_research = bool(re.search(
        r"\b(?:"
        r"recherchier\w*|"
        r"deep research|tiefe recherche|"
        r"mehrere quellen|"
        r"mehrere aktuelle quellen|"
        r"vergleiche?\s+(?:mehrere|aktuelle|neue)\s+quellen|"
        r"quellen\s+vergleichen"
        r")\b",
        value,
        re.IGNORECASE,
    ))

    comparison = any(
        marker in value
        for marker in (
            "vergleiche",
            "vergleich",
            "gegenüber",
            "gegenueber",
            "mehrere quellen",
        )
    )

    freshness = any(
        marker in value
        for marker in (
            "aktuell",
            "aktuelle",
            "aktuellen",
            "heute",
            "neueste",
            "neuesten",
            "news",
        )
    )

    return explicit_research or (comparison and freshness)

def _looks_like_cross_capability_request(
    prompt,
    conversation_context=None,
):
    """Recognize tasks combining local project work with external research."""
    value = str(prompt or "").strip().lower()

    local_project = any(
        marker in value
        for marker in (
            "mein projekt",
            "meinem projekt",
            "mein code",
            "meinem code",
            "lokaler code",
            "lokalen code",
            "workspace",
            "codebase",
        )
    )

    external = any(
        marker in value
        for marker in (
            "recherch",
            "online",
            "im web",
            "internet",
            "websuche",
            "web search",
        )
    )

    multi_step = any(
        marker in value
        for marker in (
            "danach",
            "anschließend",
            "anschliessend",
            "und recherchiere",
            "und suche",
            "vergleiche",
            "kombiniere",
            "behebt",
            "beheben",
        )
    )

    return local_project and external and multi_step

def _safe_file_context_metadata(file_context):
    """Expose only harmless file metadata to the routing manager."""
    if not isinstance(file_context, dict):
        return None

    return {
        "kind": file_context.get("kind"),
        "mime_type": (
            file_context.get("mime_type")
            or file_context.get("mime")
        ),
        "name": (
            file_context.get("name")
            or file_context.get("filename")
        ),
        "has_stored_path": bool(
            file_context.get("stored_path")
            or file_context.get("path")
        ),
    }

def _manager_route_trigger_reasons(
    prompt,
    semantic,
    file_context=None,
    conversation_context=None,
    classifier_failed=False,
):
    """Return reasons why qwen35 should review the small-router result."""
    reasons = []

    intent = str(
        (semantic or {}).get("intent") or ""
    ).strip().lower()

    try:
        confidence = float(
            (semantic or {}).get("confidence") or 0.0
        )
    except (TypeError, ValueError):
        confidence = 0.0

    requires_tools = (semantic or {}).get("requires_tools")

    if classifier_failed:
        reasons.append("small_router_failed")

    if intent not in SEMANTIC_ROUTER_INTENTS:
        reasons.append("invalid_intent")

    if confidence < SEMANTIC_ROUTER_THRESHOLD:
        reasons.append("low_confidence")

    if (
        intent in SEMANTIC_ROUTER_AGENT_INTENTS
        and requires_tools is not True
    ):
        reasons.append("agent_without_tools")

    if (
        intent == "web_search"
        and requires_tools is False
    ):
        reasons.append("web_search_without_tools")

    if (
        _looks_like_local_diagnostic(
            prompt,
            conversation_context,
        )
        and intent != "diagnostic_agent"
    ):
        reasons.append("diagnostic_conflict")

    if (
        _looks_like_coding_action(
            prompt,
            conversation_context,
        )
        and intent not in {
            "coding_agent",
            "orchestrator",
        }
    ):
        reasons.append("coding_conflict")

    if (
        _looks_like_research_request(prompt)
        and (
            intent not in {
                "research_agent",
                "orchestrator",
            }
            or requires_tools is not True
        )
    ):
        reasons.append("research_conflict")

    if (
        _looks_like_cross_capability_request(
            prompt,
            conversation_context,
        )
        and intent != "orchestrator"
    ):
        reasons.append("cross_capability_conflict")

    if (
        _looks_like_creative_chat_request(prompt)
        and intent != "normal_chat"
    ):
        reasons.append("creative_chat_conflict")

    return list(dict.fromkeys(reasons))

def semantic_manager_classifier(
    prompt,
    small_router_result,
    trigger_reasons,
    file_context=None,
    conversation_context=None,
):
    """
    Use the configured agent model as a second-stage routing judge.

    This function performs routing only. It never executes a tool.
    """
    try:
        active_workspace = (
            code_workspaces.active_workspace(
                validate=False
            )
        )
    except ValueError:
        active_workspace = None

    system_prompt = f"""
Du bist ausschließlich der zweite Routing-Judge von MLX nobby.

Du beantwortest die Nutzerfrage NICHT.
Du führst KEIN Tool aus.
Du entscheidest nur den endgültigen Routing-Intent.

Der kleine Router wurde bereits ausgeführt, aber seine Entscheidung
ist möglicherweise unsicher oder widersprüchlich.

Verfügbare Fähigkeiten:

{capability_model_text()}

Wichtige Regeln:

- Normale Wissensfragen, Beratung, kreative Texte, Geschichten,
  Rollenspiele, Roleplay, Simulationen und Dialoge gehören zu
  normal_chat, solange keine externe Recherche ausdrücklich nötig ist.

- Eine konkrete Prüfung des aktuellen lokalen Macs oder laufender
  Prozesse gehört zu diagnostic_agent.

- Eine Analyse großer Dateien, Ordner oder des lokalen Speicherplatzes
  gehört zu diagnostic_agent.

- Eine konkrete Änderung oder Untersuchung des aktiven lokalen
  Coding-Projekts gehört zu coding_agent.

- Allgemeine Programmierfragen gehören zu normal_chat.

- Eine einzelne aktuelle Webabfrage gehört zu web_search.

- Eine aktuelle mehrstufige Recherche oder ein Vergleich mehrerer
  Quellen gehört zu research_agent.

- Eine Aufgabe, die externe Recherche UND Arbeit am lokalen Projekt
  kombiniert, gehört zu orchestrator.

- Bildanalyse gehört zu vision.
- Bildänderung gehört zu image_edit.
- Bilderzeugung gehört zu image_generate.
- Bildhochskalierung mit Real-ESRGAN gehört zu image_upscale.

- requires_tools ist true für alle Intents, die tatsächlich ein Tool,
  einen Agenten, Webzugriff oder eine Spezialpipeline benötigen.
- requires_tools ist bei normal_chat false.

Sei konservativ mit autonomen Agent-Intents.
Wenn keine externe oder lokale Aktion erforderlich ist, bevorzuge
normal_chat.

Antworte ausschließlich mit genau einem gültigen JSON-Objekt:

{{"intent":"...","confidence":0.0,"requires_tools":false,"reason":"maximal 12 Wörter"}}

Erlaubte Intents:
{', '.join(sorted(SEMANTIC_ROUTER_INTENTS))}
""".strip()

    payload = {
        "prompt": str(prompt or "")[:4000],
        "small_router": small_router_result,
        "manager_trigger_reasons": trigger_reasons,
        "active_coding_workspace": bool(active_workspace),
        "file_context": _safe_file_context_metadata(
            file_context
        ),
        "conversation_context": json.loads(
            _router_context_text(
                conversation_context
            )
        ),
    }

    answer = observed_agent_llm(
        "router.manager",
        [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": json.dumps(
                    payload,
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=320,
        temperature=0.0,
    )

    parsed = parse_agent_json(answer)

    intent = str(
        parsed.get("intent") or ""
    ).strip().lower()

    aliases = {
        "image_generation": "image_generate",
        "file_analysis": "file_analyze",
    }
    intent = aliases.get(intent, intent)

    if intent not in SEMANTIC_ROUTER_INTENTS:
        raise ValueError(
            "Manager lieferte unbekannten Intent"
        )

    try:
        confidence = max(
            0.0,
            min(
                1.0,
                float(
                    parsed.get(
                        "confidence",
                        0.0,
                    )
                ),
            ),
        )
    except (TypeError, ValueError):
        confidence = 0.0

    requires_tools = parsed.get(
        "requires_tools"
    )

    if not isinstance(requires_tools, bool):
        requires_tools = (
            intent != "normal_chat"
        )

    return {
        "intent": intent,
        "confidence": confidence,
        "requires_tools": requires_tools,
        "reason": str(
            parsed.get("reason") or ""
        ).strip()[:500],
    }

def semantic_router_fallback(
    prompt,
    file_context=None,
    conversation_context=None,
):
    if _looks_like_local_diagnostic(prompt, conversation_context):
        return "diagnostic_agent"
    if _looks_like_coding_action(prompt, conversation_context):
        return "coding_agent"
    if file_context:
        return "file_analyze"
    return "normal_chat"

def classify_chat_action_details(
    prompt,
    file_context=None,
    conversation_context=None,
    classifier=None,
    manager_classifier=None,
):
    deterministic=_direct_chat_action(
        prompt,
        file_context,
        conversation_context,
    )
    if deterministic:
        return {
            "intent": deterministic,
            "confidence": 1.0,
            "reason": "Eindeutige deterministische Routing-Regel",
            "method": "deterministic",
        }

    classify = classifier or semantic_intent_classifier
    classifier_failed = False

    try:
        semantic = classify(
            prompt,
            file_context,
            conversation_context,
        )
    except Exception as exc:
        classifier_failed = True
        semantic = {
            "intent": "",
            "confidence": 0.0,
            "requires_tools": False,
            "reason": (
                "Classifier nicht verfügbar: "
                + str(exc)
            ),
        }

    small_router_result = dict(semantic)

    trigger_reasons = _manager_route_trigger_reasons(
        prompt,
        semantic,
        file_context,
        conversation_context,
        classifier_failed=classifier_failed,
    )

    # Existing tests often inject a synthetic classifier.
    # Do not unexpectedly load the real manager in those tests.
    manager = manager_classifier
    if manager is None and classifier is None:
        manager = semantic_manager_classifier

    manager_error = None
    manager_used = False

    if trigger_reasons and manager is not None:
        try:
            semantic = manager(
                prompt,
                small_router_result,
                trigger_reasons,
                file_context,
                conversation_context,
            )
            manager_used = True
        except Exception as exc:
            manager_error = str(exc)
            semantic = small_router_result

    intent = str(
        semantic.get("intent") or ""
    ).strip().lower()
    try:
        confidence=max(0.0, min(1.0, float(semantic.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence=0.0
    if intent not in SEMANTIC_ROUTER_INTENTS:
        confidence=0.0
    if confidence < SEMANTIC_ROUTER_THRESHOLD:
        fallback=semantic_router_fallback(
            prompt,
            file_context,
            conversation_context,
        )
        result = {
            "intent": fallback,
            "confidence": confidence,
            "reason": (
                semantic.get("reason")
                or "Niedrige Classifier-Confidence"
            ),
            "method": "safe_fallback",
            "classifier_intent": intent or None,
            "small_router": small_router_result,
            "manager_trigger_reasons": trigger_reasons,
        }
        if manager_error:
            result["manager_error"] = manager_error
        return result

    requires_tools=semantic.get("requires_tools")

    if (
        intent == "coding_agent"
        and requires_tools is False
        and _looks_like_coding_action(
            prompt,
            conversation_context,
        )
    ):
        requires_tools = True
    if not isinstance(requires_tools, bool):
        requires_tools=intent != "normal_chat"

    # A natural-language request may only enter an autonomous agent loop when
    # the semantic classifier explicitly confirms that tools are required.
    if intent in SEMANTIC_ROUTER_AGENT_INTENTS and not requires_tools:
        return {
            "intent": "normal_chat",
            "semantic_intent": intent,
            "confidence": confidence,
            "requires_tools": False,
            "reason": (
                str(semantic.get("reason") or "")
                or "Kein Werkzeugzugriff erforderlich"
            ),
            "method": (
                "semantic_manager_safety_fallback"
                if manager_used
                else "semantic_safety_fallback"
            ),
            "small_router": small_router_result,
            "manager_trigger_reasons": trigger_reasons,
        }

    # Vision remains part of the regular chat and VLM path.
    effective_intent="normal_chat" if intent == "vision" else intent
    if intent == "file_analyze" and not file_context:
        effective_intent="normal_chat"
    result = {
        "intent": effective_intent,
        "semantic_intent": intent,
        "confidence": confidence,
        "requires_tools": requires_tools,
        "reason": str(semantic.get("reason") or ""),
        "method": (
            "semantic_manager"
            if manager_used
            else "semantic_llm"
        ),
        "small_router": small_router_result,
        "manager_trigger_reasons": trigger_reasons,
    }

    if manager_error:
        result["manager_error"] = manager_error

    return result

def classify_chat_action(prompt, file_context=None, conversation_context=None):
    return classify_chat_action_details(
        prompt,
        file_context,
        conversation_context,
    )["intent"]


def chat_tool_result(tool, status, data=None, artifacts=None, error=None):
    return {"type": "tool_result", "tool": tool, "status": status, "data": data or {}, "artifacts": artifacts or [], "error": error}


def tool_model_switch(request):
    match = re.search(r"(?:wechsle|starte)\s+(?:auf\s+)?([a-z0-9._-]+)", request.prompt.lower())
    if not match: raise HTTPException(status_code=400, detail="Kein Modell-Alias in der Anweisung gefunden")
    return model_command(match.group(1))


def tool_pii_audit(request):
    path = Path((request.file_context or {}).get("stored_path", ""))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Referenzierte Datei ist nicht verfügbar")
    return deterministic_pii_audit(path.read_text(encoding="utf-8", errors="replace"))

def tool_knowledge_search(request):
    return knowledge.search(request.prompt)

def tool_knowledge_add(request):
    match = re.search(r"(?:indexiere)\s+(.+?)(?:\s*$)", request.prompt, re.I)
    if not match: raise HTTPException(status_code=400, detail="Kein Quellpfad angegeben")
    return knowledge.index_source(match.group(1).strip().strip("`"))

def tool_code_search(request):
    try:
        workspace_id = code_workspaces.active_workspace_id()
        return code_workspaces.search(workspace_id, request.prompt)
    except ValueError as exc:
        raise code_http_error(exc)


def image_prompt_from_request(prompt):
    """Strip the chat instruction while preserving the actual image description."""
    cleaned = re.sub(
        r"^\s*(?:bitte\s+)?(?:erstelle|generiere|erzeuge|zeichne|mach)"
        r"(?:\s+mir)?\s+(?:ein(?:e[nsr]?|en)?\s+)?"
        r"(?:(?:fotorealistisch(?:es|e)?|realistisch(?:es|e)?|schönes|tolles)\s+)?"
        r"(?:bild|foto|illustration)(?:\s+von)?\s*",
        "",
        str(prompt or ""),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^\s*(?:bitte\s+)?(?:bild|foto|illustration)\s+von\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" .") or str(prompt or "").strip()




def translate_image_prompt_to_english(prompt):
    """Translate image prompts literally to English for better model adherence."""
    value = str(prompt or "").strip()
    if not value:
        return value

    call_metrics = None
    wait_started = time.monotonic()
    try:
        with MODEL_RUNTIME_LOCK:
            queue_wait_ms = (time.monotonic() - wait_started) * 1000
            runtime = ensure_model_for_role("chat")
            role = runtime["resolved"]
            model = role.get("repo")

            if not model:
                return value

            config = load_config()
            port = int(config.get("PORT", 8000))

            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You prepare prompts for an image-generation model. "
                            "Translate the user's image description literally into English "
                            "and choose the most suitable canvas layout for the requested "
                            "composition. Preserve every concrete detail exactly, including "
                            "subject count, explicitly stated adult age, gender, nudity or "
                            "clothing, pose, appearance, environment, camera details and "
                            "artistic style. Do not add, remove, soften, censor, euphemize, "
                            "reinterpret or sanitize anything. If the prompt is already "
                            "English, preserve it. Choose exactly one layout from: "
                            "square, portrait, tall, landscape, wide. "
                            "Use square for compositions that benefit from equal dimensions; "
                            "portrait for ordinary vertical portraits and people; "
                            "tall for full-body, strongly vertical or poster-like compositions; "
                            "landscape for ordinary horizontal scenes; "
                            "wide for cinematic, panoramic or strongly horizontal compositions. "
                            "Return ONLY valid compact JSON with exactly these keys: "
                            "{\"prompt\":\"final English image prompt\","
                            "\"layout\":\"square|portrait|tall|landscape|wide\"}. "
                            "No markdown, quotes around the whole response, explanations "
                            "or commentary."
                        ),
                    },
                    {
                        "role": "user",
                        "content": value,
                    },
                ],
                "temperature": 0.0,
                "max_tokens": 700,
                "stream": False,
            }
            call_metrics = observability.ModelCallMetrics(
                purpose="image.prompt_translate",
                model=model,
                role="chat",
                alias=role.get("alias"),
                backend=role.get("backend"),
                messages=payload["messages"],
                context_sources=observability.message_context_counts(
                    payload["messages"]
                ),
                started_at=wait_started,
            )
            call_metrics.set_queue_wait(queue_wait_ms)

            upstream = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            connect_started = time.monotonic()
            with urllib.request.urlopen(upstream, timeout=180) as response:
                call_metrics.set_upstream_connect(
                    (time.monotonic() - connect_started) * 1000
                )
                result = json.loads(response.read().decode("utf-8"))

            choice = result.get("choices", [{}])[0]
            translated = choice.get("message", {}).get("content", "").strip()
            call_metrics.finish(
                usage=result.get("usage"),
                output_text=translated,
                finish_reason=choice.get("finish_reason"),
            )

            translated = translated.strip()
            if not translated:
                return value

            # Preferred response: one LLM call returns both the translated
            # image prompt and the composition-aware canvas layout.
            try:
                structured = json.loads(translated)

                if isinstance(structured, dict):
                    final_prompt = str(
                        structured.get("prompt") or ""
                    ).strip()

                    layout = str(
                        structured.get("layout") or ""
                    ).strip().lower()

                    layouts = {
                        "square": (1024, 1024),
                        "portrait": (768, 1024),
                        "tall": (768, 1024),
                        "landscape": (1024, 768),
                        "wide": (1024, 768),
                    }

                    if final_prompt and layout in layouts:
                        width, height = layouts[layout]

                        print(
                            "[image-prompt] prepared "
                            f"source_chars={len(value)} "
                            f"output_chars={len(final_prompt)} "
                            f"layout={layout} "
                            f"size={width}x{height}",
                            flush=True,
                        )

                        return {
                            "prompt": final_prompt,
                            "layout": layout,
                            "width": width,
                            "height": height,
                        }

            except (json.JSONDecodeError, TypeError, ValueError):
                pass

            # Backward-compatible fallback for old/plain-text responses.
            translated = translated.strip(' "\'')
            if not translated:
                return value

            print(
                "[image-prompt] translated "
                f"source_chars={len(value)} output_chars={len(translated)}",
                flush=True,
            )
            return translated

    except Exception as exc:
        if call_metrics is not None and call_metrics.metric["status"] == "running":
            call_metrics.fail(type(exc).__name__)
        print(
            "[image-prompt] translation failed, using original "
            f"error_type={type(exc).__name__}",
            flush=True,
        )
        return value


def web_search_query_from_prompt(prompt):
    """Remove common search-command wording but keep the real query."""
    value = str(prompt or "").strip()

    patterns = (
        r"^\s*(?:bitte\s+)?suche\s+(?:mir\s+)?(?:im\s+web|online|im\s+internet)\s+(?:nach\s+)?",
        r"^\s*(?:bitte\s+)?websuche\s+(?:nach\s+)?",
        r"^\s*(?:bitte\s+)?web\s+search\s+(?:for\s+)?",
        r"^\s*(?:bitte\s+)?schau\s+(?:online|im\s+internet)\s+(?:nach\s+)?",
    )

    for pattern in patterns:
        value = re.sub(
            pattern,
            "",
            value,
            flags=re.IGNORECASE,
        )

    return value.strip(" .,:;") or str(prompt or "").strip()


def web_host_is_safe(hostname):
    """Block localhost, private LAN, link-local and similar destinations."""
    import ipaddress
    import socket

    hostname = str(hostname or "").strip().lower().rstrip(".")

    if not hostname:
        return False

    if hostname in {
        "localhost",
        "localhost.localdomain",
    }:
        return False

    if hostname.endswith(".local"):
        return False

    try:
        infos = socket.getaddrinfo(
            hostname,
            None,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror:
        return False

    if not infos:
        return False

    for info in infos:
        address = info[4][0]

        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False

    return True


def web_url_is_safe(url):
    import urllib.parse

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False

    if parsed.username or parsed.password:
        return False

    return web_host_is_safe(parsed.hostname)


def extract_web_text(html):
    """Very small stdlib-only HTML → readable text extractor."""
    from html.parser import HTMLParser
    import html as html_module

    class TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
            self.skip_depth = 0

        def handle_starttag(self, tag, attrs):
            tag = tag.lower()

            if tag in {
                "script",
                "style",
                "noscript",
                "svg",
                "canvas",
                "template",
            }:
                self.skip_depth += 1

            if (
                self.skip_depth == 0
                and tag in {
                    "p",
                    "br",
                    "li",
                    "article",
                    "section",
                    "h1",
                    "h2",
                    "h3",
                    "h4",
                }
            ):
                self.parts.append("\n")

        def handle_endtag(self, tag):
            tag = tag.lower()

            if (
                tag in {
                    "script",
                    "style",
                    "noscript",
                    "svg",
                    "canvas",
                    "template",
                }
                and self.skip_depth > 0
            ):
                self.skip_depth -= 1

            if (
                self.skip_depth == 0
                and tag in {
                    "p",
                    "li",
                    "article",
                    "section",
                    "h1",
                    "h2",
                    "h3",
                    "h4",
                }
            ):
                self.parts.append("\n")

        def handle_data(self, data):
            if self.skip_depth == 0:
                self.parts.append(data)

    parser = TextExtractor()

    try:
        parser.feed(html)
    except Exception:
        pass

    value = html_module.unescape(
        " ".join(parser.parts)
    )

    value = re.sub(
        r"[ \t]+",
        " ",
        value,
    )

    value = re.sub(
        r"\n\s*\n+",
        "\n\n",
        value,
    )

    return value.strip()


def fetch_web_page(url, offset=0, chunk_size=18_000):
    try:
        offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        offset = 0

    try:
        chunk_size = int(chunk_size or 18_000)
    except (TypeError, ValueError):
        chunk_size = 18_000

    chunk_size = max(1_000, min(chunk_size, 18_000))
    """Safely fetch one public web page."""
    import urllib.parse

    if not web_url_is_safe(url):
        return {
            "ok": False,
            "error": "Unsichere oder interne URL blockiert",
        }

    current_url = url

    # Manually validate redirects.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(
            self,
            req,
            fp,
            code,
            msg,
            headers,
            newurl,
        ):
            return None

    opener = urllib.request.build_opener(
        NoRedirect()
    )

    for _ in range(4):
        if not web_url_is_safe(current_url):
            return {
                "ok": False,
                "error": "Redirect auf interne/unsichere URL blockiert",
            }

        request = urllib.request.Request(
            current_url,
            headers={
                "User-Agent":
                    "Mozilla/5.0 (Macintosh; MLX-Nobby/1.0)",
                "Accept":
                    "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
                "Accept-Language":
                    "de-DE,de;q=0.9,en;q=0.7",
            },
            method="GET",
        )

        try:
            response = opener.open(
                request,
                timeout=12,
            )

        except urllib.error.HTTPError as exc:
            if exc.code in {
                301,
                302,
                303,
                307,
                308,
            }:
                location = exc.headers.get(
                    "Location"
                )

                if not location:
                    return {
                        "ok": False,
                        "error": "Redirect ohne Ziel",
                    }

                current_url = urllib.parse.urljoin(
                    current_url,
                    location,
                )

                continue

            return {
                "ok": False,
                "error": f"HTTP {exc.code}",
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
            }

        with response:
            content_type = (
                response.headers
                .get("Content-Type", "")
                .lower()
            )

            if not (
                "text/html" in content_type
                or "text/plain" in content_type
                or "application/xhtml+xml" in content_type
            ):
                return {
                    "ok": False,
                    "error":
                        "Kein unterstützter Text-/HTML-Inhalt",
                }

            # Max. 1.5 MB pro Webseite.
            raw = response.read(
                1_500_001
            )

            if len(raw) > 1_500_000:
                raw = raw[:1_500_000]

            charset = (
                response.headers
                .get_content_charset()
                or "utf-8"
            )

            page = raw.decode(
                charset,
                errors="replace",
            )

            if "text/plain" in content_type:
                readable = page
            else:
                readable = extract_web_text(
                    page
                )

            readable = readable.strip()

            # ------------------------------------------------
    # Detect consent, cookie, and paywall noise
            # ------------------------------------------------

            lowered = readable.lower()

            junk_markers = (
                "cookies zustimmen",
                "cookie zustimmen",
                "cookies & tracking",
                "cookie-einstellungen",
                "cookie einstellungen",
                "consent",
                "zustimmungs-dialog",
                "zustimmungsdialog",
                "privacy center",
                "datenschutzerklärung",
                "datenschutzerklaerung",
                "personalisierte anzeigen",
                "informationen auf einem gerät speichern",
                "informationen auf einem geraet speichern",
                "bereits pur-leser",
                "golem pur",
                "werbung und tracking",
                "werbe-cookies",
                "werbecookies",
            )

            junk_hits = sum(
                1
                for marker in junk_markers
                if marker in lowered
            )

            # Prefer the snippet when consent terms dominate
            # and little usable content remains.
            if junk_hits >= 3 and len(readable) < 8_000:
                return {
                    "ok": False,
                    "url": current_url,
                    "error": "Consent-/Cookie-Seite statt Artikelinhalt erkannt",
                    "characters": len(readable),
                }

    # Extremely short pages are also unsuitable as web context.
            if len(readable) < 500:
                return {
                    "ok": False,
                    "url": current_url,
                    "error": "Zu wenig verwertbarer Seiteninhalt",
                    "characters": len(readable),
                }

    # Provide enough context for Qwen without flooding the context window.
            total_characters = len(readable)

            if offset >= total_characters:
                return {
                    "ok": False,
                    "url": current_url,
                    "error": "Offset liegt hinter dem verfügbaren Text",
                    "offset": offset,
                    "total_characters": total_characters,
                }

            end_offset = min(
                offset + chunk_size,
                total_characters,
            )

            chunk = readable[offset:end_offset]
            truncated = end_offset < total_characters


            return {
                "ok": True,
                "url": current_url,
                "content_type": content_type,
                "text": chunk,
                "characters": len(chunk),
                "total_characters": total_characters,
                "offset": offset,
                "end_offset": end_offset,
                "truncated": truncated,
                "next_offset": (
                    end_offset
                    if truncated
                    else None
                ),
            }

    return {
        "ok": False,
        "error": "Zu viele Redirects",
    }


def searxng_search_results(query, limit=8):
    """Search SearXNG and return normalized, safe public results only."""
    import urllib.parse

    query = str(query or "").strip()

    if len(query) < 2:
        raise HTTPException(
            status_code=400,
            detail="Suchbegriff fehlt",
        )

    searxng_url = (
        os.environ.get(
            "SEARXNG_URL",
            "http://127.0.0.1:8081",
        )
        .rstrip("/")
    )

    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "language": "de-DE",
        "safesearch": 0,
    })

    url = (
        searxng_url +
        "/search?" +
        params
    )

    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "MLX-Nobby/1.0",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=20,
        ) as response:
            payload = json.loads(
                response
                .read()
                .decode("utf-8")
            )

    except urllib.error.HTTPError as exc:
        detail = (
            exc.read()
            .decode(
                "utf-8",
                errors="replace",
            )
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "SearXNG HTTP-Fehler "
                f"{exc.code}: "
                f"{detail[:300]}"
            ),
        ) from exc

    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "SearXNG nicht erreichbar: "
                f"{exc.reason}"
            ),
        ) from exc

        # SearXNG reports temporarily blocked or unavailable engines
        # separately. Pass this information to the agent so that
        # "zero matches" is not confused with "no results available."
    unresponsive_engines = []

    for item in payload.get("unresponsive_engines", []):
        if isinstance(item, (list, tuple)):
            engine = str(item[0] if len(item) > 0 else "").strip()
            reason = str(item[1] if len(item) > 1 else "").strip()
        elif isinstance(item, dict):
            engine = str(
                item.get("engine")
                or item.get("name")
                or ""
            ).strip()
            reason = str(
                item.get("reason")
                or item.get("error")
                or ""
            ).strip()
        else:
            engine = str(item or "").strip()
            reason = ""

        if engine:
            unresponsive_engines.append({
                "engine": engine[:100],
                "reason": reason[:300],
            })

    normalized = []

    for item in payload.get("results", []):
        if not isinstance(item, dict):
            continue

        title = str(
            item.get("title") or ""
        ).strip()

        result_url = str(
            item.get("url") or ""
        ).strip()

        content = str(
            item.get("content") or ""
        ).strip()

        if not title or not result_url:
            continue

        # Do not pass local or internal URLs to the agent.
        if not web_url_is_safe(result_url):
            continue

        engines = item.get("engines")

        if not isinstance(engines, list):
            engines = []

        normalized.append({
            "title": title[:500],
            "url": result_url[:2000],
            "snippet": content[:1200],
            "engine": str(
                item.get("engine") or ""
            )[:100],
            "engines": [
                str(engine)[:100]
                for engine in engines[:5]
            ],
            "published_date":
                item.get("publishedDate")
                or item.get("pubdate")
                or None,
            "score":
                item.get("score"),
        })

        if len(normalized) >= max(1, min(int(limit), 20)):
            break

    return {
        "query": query,
        "provider": "SearXNG",

        "unresponsive_engines": unresponsive_engines,
        "search_degraded": bool(unresponsive_engines),
        "count": len(normalized),
        "results": normalized,
    }


def tool_search_web(request):
    """
    Granular agent tool:
    Search the web without loading the result pages yet.
    """
    query = web_search_query_from_prompt(
        request.prompt
    )

    result = searxng_search_results(
        query,
        limit=8,
    )

    results = result.get("results")

    if isinstance(results, list):
        result["results"] = rerank_technical_web_results(
            query,
            results,
        )

    return result


def tool_fetch_url(request):
    """
    Granular agent tool:
    Load one specific public URL.

    Optional:
        instruction="offset=18000"
    """
    url = str(
        request.prompt or ""
    ).strip()

    if not url:
        raise HTTPException(
            status_code=400,
            detail="URL fehlt",
        )

    offset = 0

    instruction = str(
        getattr(request, "instruction", None) or ""
    ).strip()

    if instruction:
        match = re.search(
            r"(?:^|\b)offset\s*=\s*(\d+)(?:\b|$)",
            instruction,
            flags=re.IGNORECASE,
        )

        if match:
            offset = int(match.group(1))

    result = fetch_web_page(
        url,
        offset=offset,
    )

    return {
        "requested_url": url,
        "requested_offset": offset,
        **result,
    }


def rerank_technical_web_results(query, results):
    """
    Promote likely primary sources for technical research and demote
    common secondary or profile sources.
    """
    from urllib.parse import urlsplit

    value = str(query or "").lower()

    technical_markers = (
        "documentation",
        "docs",
        "github",
        "repository",
        "repo",
        "framework",
        "library",
        "api",
        "server",
        "installation",
        "configuration",
        "konfiguration",
        "release",
        "best practice",
        "best-practice",
        "best practices",
        "inference",
        "inferenz",
    )

    if not any(marker in value for marker in technical_markers):
        return results

    def score(item):
        url = str(item.get("url") or "")
        title = str(item.get("title") or "").lower()

        try:
            host = urlsplit(url).hostname or ""
        except Exception:
            host = ""

        host = host.lower()
        points = 0

    # Common primary sources
        if host == "github.com" or host.endswith(".github.io"):
            points += 100

        if "docs." in host or "documentation" in host:
            points += 80

        if "/docs" in url.lower():
            points += 50

        if "/releases" in url.lower():
            points += 40

        if "official" in title:
            points += 25

    # Common weak secondary sources
        if "linkedin.com" in host:
            points -= 120

        if "medium.com" in host:
            points -= 40

        if "reddit.com" in host:
            points -= 25

        # Generische SEO-/Blogseiten leicht abwerten
        weak_hosts = (
            "nevercodealone.de",
        )

        if any(host.endswith(domain) for domain in weak_hosts):
            points -= 80

    # Give the original SearXNG score a small weight
        try:
            points += float(item.get("score") or 0)
        except Exception:
            pass

        return points

    return sorted(
        results,
        key=score,
        reverse=True,
    )


def tool_web_search(request):
    """
    Convenience tool for regular chat:
    Search and automatically retrieve the top three pages.
    """
    query = web_search_query_from_prompt(
        request.prompt
    )

    result = searxng_search_results(
        query,
        limit=8,
    )

    results = result.get("results")

    if isinstance(results, list):
        results = rerank_technical_web_results(
            query,
            results,
        )

        query_lower = query.lower()

        technical_markers = (
            "documentation",
            "docs",
            "github",
            "repository",
            "repo",
            "framework",
            "library",
            "api",
            "server",
            "installation",
            "configuration",
            "konfiguration",
            "release",
            "best practice",
            "best-practice",
            "best practices",
            "inference",
            "inferenz",
        )

        is_technical = any(
            marker in query_lower
            for marker in technical_markers
        )

        if is_technical:
            # Use a concise technical GitHub search instead of the site: operator.
            query_words = [
                word
                for word in re.findall(
                    r"[A-Za-z0-9_.+-]+",
                    query,
                )
                if word.lower() not in {
                    "official",
                    "documentation",
                    "docs",
                    "repository",
                    "repo",
                    "github",
                    "best",
                    "practice",
                    "practices",
                    "local",
                    "python",
                    "inference",
                    "server",
                    "configuration",
                    "konfiguration",
                }
            ]
        # Search known technical ecosystems using their
        # canonical search terms.
            if re.search(r"\bmlx(?:-lm)?\b", query.lower()):
                primary_query = "mlx-lm"
            else:
                primary_terms = query_words[:4]
                primary_query = " ".join(
                    primary_terms + ["github"]
                ).strip()

            primary = searxng_search_results(
                primary_query,
                limit=8,
            )

            primary_results = primary.get("results")

            if isinstance(primary_results, list):
                merged = []
                seen = set()

        # Prioritize primary sources.
                for item in primary_results + results:
                    if not isinstance(item, dict):
                        continue

                    url = str(item.get("url") or "").strip()

                    if not url:
                        continue

                    try:
                        parts = urlsplit(url)
                        key = (
                            parts.scheme.lower(),
                            parts.netloc.lower(),
                            parts.path.rstrip("/"),
                            parts.query,
                        )
                    except Exception:
                        key = url.rstrip("/")

                    if key in seen:
                        continue

                    seen.add(key)
                    merged.append(item)

                results = rerank_technical_web_results(
                    query,
                    merged,
                )

                result["primary_source_query"] = primary_query
                result["primary_source_count"] = len(
                    primary_results
                )

        result["results"] = results[:12]

    fetched_count = 0

    for item in result["results"][:3]:
        fetched = fetch_web_page(
            item["url"]
        )

        item["fetch"] = fetched

        if fetched.get("ok"):
            fetched_count += 1

    result["fetched_count"] = fetched_count

    return result


def _image_source_path(request):
    file_context = request.file_context or {}
    stored_path = str(file_context.get("stored_path") or "").strip()

    if stored_path:
        source = Path(stored_path).expanduser()
    else:
        artifact_id = (
            file_context.get("artifact_id")
            or request.active_artifact_id
        )
        source = _resolve_image_artifact_source(artifact_id)

    if not source.is_file():
        raise HTTPException(
            status_code=404,
            detail="Referenziertes Bild ist nicht verfügbar",
        )

    return source



def normalize_image_edit_prompt(prompt):
    """
    Expand short, common image-edit instructions into precise English
    instructions for Qwen Image Edit without requiring another LLM call.

    Longer or more specific prompts are preserved to avoid changing
    user intent.
    """
    value = str(prompt or "").strip()

    if not value:
        return value

    normalized = re.sub(r"\s+", " ", value).strip()
    lower = normalized.casefold()

    # Preserve detailed prompts. They already contain enough intent and
    # should not be rewritten heuristically.
    if len(normalized) >= 120:
        return normalized

    rules = (
        (
            (
                "tattoo entfernen",
                "tattoos entfernen",
                "tatoo entfernen",
                "tatoos entfernen",
                "tattoo weg",
                "tattoos weg",
                "tatoo weg",
                "tatoos weg",
            ),
            (
                "Remove all visible tattoos from the person's skin, "
                "including partially visible tattoos. Reconstruct every "
                "affected area with natural, realistic skin matching the "
                "surrounding skin tone, texture, lighting and anatomy. "
                "Preserve the person's identity, facial features, body shape, "
                "pose, clothing, background and all unrelated image details."
            ),
        ),
        (
            (
                "hintergrund entfernen",
                "entferne den hintergrund",
                "remove background",
            ),
            (
                "Remove the entire background cleanly while preserving the "
                "main subject, fine edges, hair and all foreground details. "
                "Do not alter the subject."
            ),
        ),
        (
            (
                "hintergrund unscharf",
                "hintergrund unscharf machen",
                "mach den hintergrund unscharf",
                "blur background",
            ),
            (
                "Apply a natural shallow depth-of-field blur to the background "
                "while keeping the main subject perfectly sharp. Preserve the "
                "subject's identity, details, lighting and colors."
            ),
        ),
        (
            (
                "augen öffnen",
                "öffne die augen",
                "open eyes",
            ),
            (
                "Open the person's eyes naturally and realistically. Preserve "
                "identity, eye color, facial proportions, expression, lighting "
                "and every unrelated image detail."
            ),
        ),
        (
            (
                "zähne heller",
                "zähne aufhellen",
                "hellere zähne",
                "whiten teeth",
            ),
            (
                "Brighten the teeth subtly and naturally without making them "
                "artificially white. Preserve tooth shape, facial identity, "
                "skin tone, lighting and all unrelated image details."
            ),
        ),
        (
            (
                "bart weniger grau",
                "weniger grauer bart",
                "bart dunkler",
            ),
            (
                "Reduce the visible gray in the beard naturally while "
                "preserving the beard shape, individual hair texture, facial "
                "identity, skin tone, lighting and all unrelated image details."
            ),
        ),
    )

    for phrases, expanded in rules:
        if any(phrase in lower for phrase in phrases):
            return expanded

    return normalized


_IMAGE_EDIT_OPTIMIZER_REFUSAL_PATTERN = re.compile(
    r"""
    (?:
        \bich\s+kann\b.{0,100}\b(?:leider\s+)?nicht\s+
        (?:erf(?:ü|ue)llen|helfen|unterst(?:ü|ue)tzen)\b
        |
        \bals\s+(?:eine?\s+)?ki(?:[-\s]?assistent(?:in)?)?\b
        |
        \bi\s+can(?:not|['’]t)\s+
        (?:comply|help(?:\s+with)?|fulfill)\b
        |
        \bi(?:\s+am|['’]m)\s+unable\s+to\b
        |
        \bas\s+an?\s+ai(?:\s+assistant)?\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _is_image_edit_optimizer_refusal(content):
    return bool(
        _IMAGE_EDIT_OPTIMIZER_REFUSAL_PATTERN.search(
            str(content or "")
        )
    )


def optimize_image_edit_prompt(prompt):
    """Compile an image-edit instruction with the local chat model."""
    original = re.sub(
        r"\s+",
        " ",
        str(prompt or ""),
    ).strip()
    fallback = normalize_image_edit_prompt(original)

    if not original:
        return fallback

    messages = [
        {
            "role": "system",
            "content": (
                "You are an image-edit instruction compiler. Convert the "
                "user's instruction into precise English suitable for an "
                "image-editing model. Preserve every requested edit, all "
                "negations, exclusions, relationships, and constraints. "
                "Handle every requested edit when the instruction contains "
                "multiple changes. Never add unrelated edits, remove a "
                "requested edit, or reinterpret the user's intent. Expand "
                "short or vague instructions only enough to make the requested "
                "visual change concrete. Explicitly preserve unrelated image "
                "details where appropriate. Preserve identity unless the user "
                "explicitly requests an identity change. Preserve pose, "
                "anatomy, clothing, lighting, composition, and background "
                "unless the user asks to modify them. Return only the final "
                "English image-edit prompt. Do not output commentary, "
                "markdown, quotes, explanations, prefixes, or reasoning."
            ),
        },
        {
            "role": "user",
            "content": original,
        },
    ]
    wait_started = time.monotonic()
    call_metrics = observability.ModelCallMetrics(
        purpose="image.edit_prompt_optimize",
        role="chat",
        messages=messages,
        context_sources=observability.message_context_counts(
            messages
        ),
        started_at=wait_started,
    )

    def use_fallback(reason):
        if call_metrics.metric["status"] == "running":
            call_metrics.fail(reason)
        print(
            "[image-edit-prompt] optimization failed, using fallback "
            f"error_type={reason}",
            flush=True,
        )
        return fallback

    try:
        with MODEL_RUNTIME_LOCK:
            call_metrics.set_queue_wait(
                (time.monotonic() - wait_started) * 1000
            )
            runtime = ensure_model_for_role("chat")
            role = runtime["resolved"]
            model = role.get("repo")

            if not model:
                return use_fallback("model_unavailable")

            call_metrics.set_model(
                model=model,
                role="chat",
                alias=role.get("alias"),
                backend=role.get("backend"),
            )

            config = load_config()
            port = int(config.get("PORT", 8000))
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.0,
                "max_tokens": 650,
                "stream": False,
                "chat_template_kwargs": {
                    "enable_thinking": False,
                },
            }
            upstream = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            connect_started = time.monotonic()
            with urllib.request.urlopen(
                upstream,
                timeout=180,
            ) as response:
                call_metrics.set_upstream_connect(
                    (time.monotonic() - connect_started) * 1000
                )
                result = json.loads(
                    response.read().decode("utf-8")
                )

            if not isinstance(result, dict):
                return use_fallback("malformed_response")
            choices = result.get("choices")
            if not isinstance(choices, list) or not choices:
                return use_fallback("missing_choices")
            choice = choices[0]
            if not isinstance(choice, dict):
                return use_fallback("malformed_choice")
            message = choice.get("message")
            if not isinstance(message, dict):
                return use_fallback("missing_message")
            content = message.get("content")
            if not isinstance(content, str):
                return use_fallback("missing_content")

            optimized = re.sub(
                r"\s+",
                " ",
                content.strip().strip("\"'“”‘’"),
            ).strip()
            lower = optimized.casefold()
            if not optimized:
                return use_fallback("empty_content")
            if len(optimized) > 6000:
                return use_fallback("response_too_large")
            if _is_image_edit_optimizer_refusal(optimized):
                return use_fallback("optimizer_refusal_fallback")
            if (
                not re.search(r"[A-Za-z]", optimized)
                or "<think" in lower
                or "</think>" in lower
                or optimized.startswith(("```", "{", "[", "#"))
                or re.match(
                    r"^(?:(?:here(?:'s| is)\s+(?:the\s+)?)?"
                    r"(?:optimized\s+)?(?:image[- ]edit\s+)?prompt)\s*:",
                    optimized,
                    re.IGNORECASE,
                )
            ):
                return use_fallback("malformed_content")
            if choice.get("finish_reason") == "length":
                return use_fallback("truncated_response")

            call_metrics.finish(
                usage=result.get("usage"),
                output_text=optimized,
                finish_reason=choice.get("finish_reason"),
            )
            print(
                "[image-edit-prompt] optimized "
                f"source_chars={len(original)} "
                f"output_chars={len(optimized)}",
                flush=True,
            )
            return optimized

    except Exception as exc:
        return use_fallback(type(exc).__name__)


def _image_edit_payload(request):
    source = _image_source_path(request)

    options = dict(request.image_options or {})
    allowed = {
        "prompt",
        "model",
        "steps",
        "guidance",
        "seed",
    }
    if set(options) - allowed:
        raise HTTPException(
            422,
            "Unbekannte Bildparameter",
        )

    payload = {
        "prompt": (
            options["prompt"]
            if "prompt" in options
            else optimize_image_edit_prompt(request.prompt)
        ),
        "source_path": str(source),
        "model": "mflux-qwen-image-edit-2511",
    }

    payload.update(options)

    return payload


def _image_upscale_payload(request):
    source = _image_source_path(request)
    options = dict(request.image_options or {})
    allowed = {"preset", "scale", "tile"}

    if set(options) - allowed:
        raise HTTPException(
            422,
            "Unbekannte Upscale-Parameter",
        )

    scale = options.pop("scale", None)
    preset = options.get("preset")
    preset_scales = {
        "photo-2x": 2,
        "photo-4x": 4,
        "anime-4x": 4,
    }

    if scale is not None:
        if scale not in {2, 4}:
            raise HTTPException(
                422,
                "Upscale scale muss 2 oder 4 sein",
            )
        scale = int(scale)
        if preset is None:
            options["preset"] = (
                "photo-2x" if scale == 2 else "photo-4x"
            )
        elif preset_scales.get(preset) != scale:
            raise HTTPException(
                422,
                "Upscale preset und scale widersprechen sich",
            )

    return {
        "source_path": str(source),
        **options,
    }


def _resolve_image_artifact_source(artifact_id):
    """Resolve a managed image artifact without accepting a client path."""
    if not isinstance(artifact_id, str):
        raise HTTPException(
            status_code=404,
            detail=(
                "Bitte hänge ein Bild an oder bearbeite zuerst "
                "ein vorhandenes Bild."
            ),
        )

    match = IMAGE_ARTIFACT_ID_PATTERN.fullmatch(artifact_id)
    if not match:
        raise HTTPException(
            status_code=422,
            detail="Ungültige Image-Artifact-ID",
        )

    image_directory = IMAGE_DIRECTORY.resolve()
    source = (
        image_directory / f"{match.group('image_id')}.png"
    ).resolve()

    if source.parent != image_directory:
        raise HTTPException(
            status_code=422,
            detail="Ungültige Image-Artifact-ID",
        )
    if not source.is_file():
        raise HTTPException(
            status_code=404,
            detail="Referenziertes Bild ist nicht verfügbar",
        )

    try:
        with source.open("rb") as handle:
            header = handle.read(33)
    except OSError as exc:
        raise HTTPException(
            status_code=404,
            detail="Referenziertes Bild ist nicht verfügbar",
        ) from exc

    if (
        len(header) != 33
        or not header.startswith(b"\x89PNG\r\n\x1a\n")
        or header[8:12] != b"\x00\x00\x00\r"
        or header[12:16] != b"IHDR"
        or int.from_bytes(header[16:20], "big") <= 0
        or int.from_bytes(header[20:24], "big") <= 0
        or int.from_bytes(header[29:33], "big")
        != zlib.crc32(header[12:29])
    ):
        raise HTTPException(
            status_code=422,
            detail="Image-Artifact ist kein gültiges PNG",
        )

    return source


def _automatic_image_dimensions(prompt):
    """Choose dimensions from the requested image composition."""
    value = str(prompt or "").lower()

    square_markers = (
        "square",
        "icon",
        "logo",
        "avatar",
        "profile picture",
        "product shot",
    )

    landscape_markers = (
        "landscape",
        "panorama",
        "scenery",
        "cityscape",
        "wide shot",
        "cinematic wide",
        "mountains",
        "beach",
        "forest",
    )

    portrait_markers = (
        "portrait",
        "full body",
        "full-body",
        "standing",
        "person",
        "woman",
        "man",
        "girl",
        "boy",
        "model",
        "headshot",
        "fashion",
    )

    # Specific composition wins before generic person markers.
    if any(marker in value for marker in square_markers):
        return 1024, 1024

    if any(marker in value for marker in landscape_markers):
        return 1024, 768

    if any(marker in value for marker in portrait_markers):
        return 768, 1024

    return 1024, 1024


def _image_generate_payload(request):
    source_prompt = image_prompt_from_request(request.prompt)
    prepared = translate_image_prompt_to_english(source_prompt)

    if isinstance(prepared, dict):
        prompt = str(prepared.get("prompt") or "").strip()
        width = int(prepared.get("width") or 0)
        height = int(prepared.get("height") or 0)

        if width <= 0 or height <= 0:
            width, height = _automatic_image_dimensions(prompt)
    else:
        prompt = str(prepared or "").strip()
        width, height = _automatic_image_dimensions(prompt)

    if len(prompt) < 3:
        raise HTTPException(
            status_code=400,
            detail="Bitte beschreibe das gewünschte Bild",
        )

    payload = {
        "prompt": prompt,
        "model": "auto",
        "width": width,
        "height": height,
    }

    if request.image_options:
        if set(request.image_options) - {
            "prompt",
            "negative_prompt",
            "model",
            "width",
            "height",
            "steps",
            "guidance",
            "seed",
        }:
            raise HTTPException(422, "Unbekannte Bildparameter")

        # Explicit user options always override automatic defaults.
        payload.update(request.image_options)

    return payload


def _image_artifact(result, action):
    image_id = str(result.get("id", ""))
    image_path = Path(str(result.get("path", "")))

    if (
        not IMAGE_ID_PATTERN.fullmatch(image_id)
        or image_path.parent != IMAGE_DIRECTORY
        or image_path.suffix != ".png"
    ):
        raise HTTPException(
            status_code=502,
            detail="Ungültige Antwort vom Image-Service",
        )

    artifact = {
        "artifact_id": f"image-{image_id}",
        "image_id": image_id,
        "name": f"{image_id}.png",
        "path": str(image_path),
        "mime_type": "image/png",
        "width": result.get("width"),
        "height": result.get("height"),
        "prompt": result.get("prompt"),
        "model": result.get("model"),
        "seed": result.get("seed"),
        "steps": result.get("steps"),
        "guidance": result.get("guidance"),
        "provider": result.get("provider"),
        "model_family": result.get("model_family"),
        "quantization": result.get("quantization"),
        "loras": result.get("loras", []),
        "created_at": result.get("created_at", time.time()),
        "source_job_id": image_id,
    }
    if action in {"image_edit", "image_upscale"}:
        artifact["source_path"] = result.get("source_path")
    if action == "image_upscale":
        artifact.update({
            "source_width": result.get("source_width"),
            "source_height": result.get("source_height"),
            "scale": result.get("scale"),
            "preset": result.get("preset"),
            "tile": result.get("tile"),
        })
    return artifact


def tool_image_edit(request):
    payload = _image_edit_payload(request)

    result = image_api.request(
        "POST",
        "/edit",
        payload,
        timeout=900,
    )
    return {"image": _image_artifact(result, "image_edit")}


def tool_image_generate(request):
    payload = _image_generate_payload(request)
    result = image_generate_api(payload)
    return {"image": _image_artifact(result, "image_generate")}


def _start_chat_image_job(action, request):
    payload_builders = {
        "image_generate": _image_generate_payload,
        "image_edit": _image_edit_payload,
        "image_upscale": _image_upscale_payload,
    }
    payload_builder = payload_builders.get(action)
    if payload_builder is None:
        raise HTTPException(
            422,
            "Unbekannte Image-Job-Aktion",
        )
    payload = payload_builder(request)

    if action == "image_generate" and payload.get("model", "auto") == "auto":
        payload["model"] = load_model_roles()["image"]
    return image_api.request(
        "POST",
        "/jobs",
        {
            "operation": action.removeprefix("image_"),
            "payload": payload,
        },
        timeout=10,
    )


def _image_job_tool_result(job):
    action = "image_" + str(job.get("operation") or "")
    status = str(job.get("status") or "failed")
    data = {"job": job}
    artifacts = []

    if status == "completed":
        artifact = _image_artifact(job.get("result") or {}, action)
        data["image"] = artifact
        artifacts.append(artifact)

    return chat_tool_result(
        action,
        status,
        data,
        artifacts=artifacts,
        error=job.get("error"),
    )


@app.get("/api/image/health")
def image_health_api():
    return image_api.request("GET", "/health")


@app.get("/api/image/models")
def image_models_api():
    data = image_api.request("GET", "/models")
    configured = load_model_roles()["image"]
    return data | {"role": configured, "effective_model": data["default_model"] if configured == "auto" else configured}


@app.get("/api/image/models/{model_id}")
def image_model_api(model_id: str):
    return image_api.request("GET", "/models/" + image_api.model_id(model_id))


@app.post("/api/image/models")
def image_add_api(request: dict):
    return image_api.request("POST", "/models", request)


@app.put("/api/image/models/{model_id}")
def image_update_api(model_id: str, request: dict):
    if request.get("enabled") is False and load_model_roles()["image"] == model_id:
        raise HTTPException(409, "Zuerst die Image-Rolle auf auto oder ein anderes Modell umstellen")
    return image_api.request("PUT", "/models/" + image_api.model_id(model_id), request)


@app.put("/api/image/role")
def image_role_api(request: dict):
    return set_model_role("image", {"alias": request.get("model", "auto")})


@app.post("/api/image/models/{model_id}/activate")
def image_activate_api(model_id: str):
    return image_api.request("POST", "/models/" + image_api.model_id(model_id) + "/activate", {})


@app.post("/api/image/unload")
def image_unload_api():
    return image_api.request("POST", "/unload", {})


@app.get("/api/image/jobs/{job_id}")
def image_job_api(job_id: str):
    job = image_api.request(
        "GET",
        "/jobs/" + image_api.job_id(job_id),
    )
    return _image_job_tool_result(job)


@app.post("/api/image/jobs/{job_id}/cancel")
def image_job_cancel_api(job_id: str):
    job = image_api.request(
        "POST",
        "/jobs/" + image_api.job_id(job_id) + "/cancel",
        {},
        timeout=15,
    )
    return _image_job_tool_result(job)


@app.post("/api/image/generate")
def image_generate_api(request: dict):
    payload = dict(request)
    if payload.get("model", "auto") == "auto":
        payload["model"] = load_model_roles()["image"]
    return image_api.request("POST", "/generate", payload, timeout=900)


@app.get("/api/images/{image_id}")
def image_download(image_id: str, download: bool = False):
    if not IMAGE_ID_PATTERN.fullmatch(image_id):
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")
    image_path = IMAGE_DIRECTORY / f"{image_id}.png"
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")
    return FileResponse(
        image_path,
        media_type="image/png",
        filename=image_path.name if download else None,
    )


TOOLS = {
    "model_list": lambda request: models(),
    "model_switch": tool_model_switch,
    "model_restart": lambda request: server_command("restart"),
    "thinking_on": lambda request: thinking_command("on"),
    "thinking_off": lambda request: thinking_command("off"),
    "system_status": lambda request: {"status": status(), "system": system()},
    "logs_query": lambda request: logs_all(80),
    "batch_status": lambda request: get_batch_jobs(),
    "pii_audit": tool_pii_audit,
    "knowledge_search": tool_knowledge_search,
    "knowledge_add": tool_knowledge_add,
    "knowledge_status": lambda request: knowledge.status(),
    "code_search": tool_code_search,
    "image_generate": tool_image_generate,
    "image_edit": tool_image_edit,
    "web_search": tool_web_search,
    "search_web": tool_search_web,
    "fetch_url": tool_fetch_url,
}

@app.get('/api/code/workspaces')
def code_workspace_list():
    try:
        return {
            'workspaces':code_workspaces.list_workspaces(),
            'active_workspace':code_workspaces.active_workspace(validate=False),
        }
    except ValueError as exc:
        raise code_http_error(exc)
@app.post('/api/code/workspaces')
def code_workspace_add(request: CodeWorkspaceRequest):
    try: return code_workspaces.add_workspace(request.path,request.name,request.test_commands,activate=True)
    except ValueError as exc: raise code_http_error(exc)
@app.post('/api/code/workspaces/pick')
def code_workspace_pick():
    try: return pick_code_workspace_folder()
    except ValueError as exc: raise code_http_error(exc)
@app.get('/api/code/workspaces/active')
def code_workspace_active():
    try: return {'active_workspace':code_workspaces.active_workspace()}
    except ValueError as exc: raise code_http_error(exc)
@app.post('/api/code/workspaces/{workspace_id}/activate')
def code_workspace_activate(workspace_id: str):
    try: return code_workspaces.set_active_workspace(workspace_id)
    except ValueError as exc: raise code_http_error(exc)
@app.delete('/api/code/workspaces/{workspace_id}')
def code_workspace_remove(workspace_id: str):
    try: return code_workspaces.remove_workspace(workspace_id)
    except ValueError as exc: raise code_http_error(exc)
@app.post('/api/code/workspaces/{workspace_id}/refresh')
def code_workspace_refresh(workspace_id: str):
    try: return code_workspaces.refresh(workspace_id)
    except ValueError as exc: raise code_http_error(exc)
@app.get('/api/code/workspaces/{workspace_id}/detect-tests')
def code_workspace_detect_tests(workspace_id: str):
    try:
        return code_workspaces.detect_test_commands(workspace_id)
    except ValueError as exc:
        raise code_http_error(exc)

@app.get('/api/code/workspaces/{workspace_id}')
def code_workspace_status(workspace_id: str):
    try: return code_workspaces.status(workspace_id)
    except ValueError as exc: raise code_http_error(exc)
@app.post('/api/code/read')
def code_read(request: CodeReadRequest):
    try: return code_workspaces.read(request.workspace_id,request.path,request.start_line,request.end_line)
    except ValueError as exc: raise code_http_error(exc)
@app.post('/api/code/search')
def code_search(request: CodeSearchRequest):
    try: return code_workspaces.search(request.workspace_id,request.query)
    except ValueError as exc: raise code_http_error(exc)
@app.post('/api/code/patches')
def code_patch(request: CodePatchRequest):
    try: return code_workspaces.create_patch(request.workspace_id,request.instruction,request.files)
    except (KeyError, TypeError, ValueError) as exc:
        error = exc if isinstance(exc, ValueError) else ValueError("PATCH_INVALID")
        raise code_http_error(error)
@app.get('/api/code/patches/{patch_id}/diff')
def code_diff(patch_id: str):
    try: return code_workspaces.diff(patch_id)
    except ValueError as exc: raise code_http_error(exc)
@app.post('/api/code/patches/{patch_id}/test')
def code_test(patch_id: str):
    try: return code_workspaces.test(patch_id)
    except ValueError as exc: raise code_http_error(exc)
@app.post('/api/code/patches/{patch_id}/apply')
def code_apply(patch_id: str, request: CodeApprovalRequest):
    try: return code_workspaces.apply(patch_id,request.approved)
    except ValueError as exc: raise code_http_error(exc)
@app.post('/api/code/patches/{patch_id}/revert')
def code_revert(patch_id: str):
    try: return code_workspaces.revert(patch_id)
    except ValueError as exc: raise code_http_error(exc)


@app.get("/api/knowledge/select-folder")
def knowledge_select_folder():
    if sys.platform != "darwin":
        raise HTTPException(
            status_code=501,
            detail="Die Ordnerauswahl wird derzeit nur unter macOS unterstützt.",
        )

    script = """
    try
        set selectedFolder to choose folder with prompt "Wissensquelle auswählen"
        return POSIX path of selectedFolder
    on error number -128
        return ""
    end try
    """

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=504,
            detail="Ordnerauswahl wurde nicht abgeschlossen.",
        ) from exc

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=result.stderr.strip() or "Ordnerauswahl fehlgeschlagen.",
        )

    path = result.stdout.strip()

    if not path:
        return {
            "cancelled": True,
            "path": None,
        }

    folder = Path(path).expanduser().resolve()

    if not folder.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Der ausgewählte Pfad ist kein Ordner.",
        )

    return {
        "cancelled": False,
        "path": str(folder),
        "name": folder.name,
    }


@app.get("/api/knowledge/status")
def knowledge_status(): return knowledge.status()

@app.post("/api/knowledge/sources")
def knowledge_add(request: KnowledgeSourceRequest):
    try: return knowledge.index_source(request.path, request.name, request.force)
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc))

@app.post("/api/knowledge/search")
def knowledge_search(request: KnowledgeSearchRequest):
    return knowledge.search(request.query, request.scope)


@app.post("/api/knowledge/sources/{source_id}/enable")
def knowledge_source_enable(source_id: str):
    try:
        return knowledge.set_source_enabled(source_id, True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/knowledge/sources/{source_id}/disable")
def knowledge_source_disable(source_id: str):
    try:
        return knowledge.set_source_enabled(source_id, False)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/knowledge/sources/{source_id}/reindex")
def knowledge_source_reindex(source_id: str):
    try:
        return knowledge.reindex_source(source_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/knowledge/sources/{source_id}")
def knowledge_source_delete(source_id: str):
    try:
        return knowledge.delete_source(source_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/profile")
def user_profile_get():
    return profile.load()


@app.put("/api/profile")
def user_profile_put(request: UserProfileRequest):
    return profile.save(request.model_dump())


@app.get("/api/profile/context")
def user_profile_context():
    return {
        "enabled": profile.load().get("enabled", True),
        "context": profile.context(),
    }

def _semantic_agent_route_allowed(
    routing,
    prompt,
    file_context=None,
    conversation_context=None,
):
    intent = str(routing.get("intent") or "")
    confidence = float(routing.get("confidence") or 0.0)
    requires_tools = routing.get("requires_tools") is True
    value = str(prompt or "").strip().lower()

    if intent not in SEMANTIC_ROUTER_AGENT_INTENTS:
        return True

    if not requires_tools:
        return False

    deterministic = _deterministic_chat_action(
        prompt,
        file_context,
        conversation_context,
    )

    if deterministic == intent:
        return True

    manager_verified = (
        routing.get("method") == "semantic_manager"
        and confidence >= 0.90
        and requires_tools
    )

    if intent == "diagnostic_agent":
        return (
            confidence >= 0.90
            and _looks_like_local_diagnostic(
                prompt,
                conversation_context,
            )
        )

    if intent == "coding_agent":
        return (
            confidence >= 0.90
            and _looks_like_coding_action(
                prompt,
                conversation_context,
            )
        )

    if intent == "research_agent":
        explicit_research = bool(re.search(
            r"\b(?:recherchier|recherche|durchsuch|"
            r"vergleiche?\s+(?:aktuell|neu|mehrere)|"
            r"aktuelle?\s+(?:quellen|informationen|news|änderungen|aenderungen))\w*\b",
            value,
        ))
        return (
            confidence >= 0.90
            and (
                explicit_research
                or (
                    manager_verified
                    and _looks_like_research_request(
                        prompt
                    )
                )
            )
        )

    if intent == "orchestrator":
        return (
            deterministic == "orchestrator"
            or (
                manager_verified
                and _looks_like_cross_capability_request(
                    prompt,
                    conversation_context,
                )
            )
        )

    return False

@app.post("/api/chat/route")
@observability.observed_turn
def route_chat_action(request: ChatActionRequest):
    routing_file_context = _image_source_routing_context(request)
    direct = _direct_chat_action(
        request.prompt,
        routing_file_context,
        request.conversation_context,
    )

    if direct is not None:
        return {
            "intent": direct,
            "confidence": 1.0,
            "requires_tools": direct != "normal_chat",
            "reason": "Eindeutige deterministische Route",
            "method": "deterministic_direct",
        }

    return classify_chat_action_details(
        request.prompt,
        routing_file_context,
        request.conversation_context,
    )



def _looks_like_image_edit_request(prompt):
    value = str(prompt or "").strip()

    if not value:
        return False

    if _IMAGE_QUESTION_PATTERN.search(value):
        return False

    if _IMAGE_EDIT_VERB_PATTERN.search(value):
        return True

    if _IMAGE_EDIT_FOLLOWUP_PATTERN.search(value):
        return True

    if (
        _IMAGE_EDIT_MAKE_PATTERN.search(value)
        and _IMAGE_EDIT_MODIFIER_PATTERN.search(value)
    ):
        return True

    return bool(
        (
            re.search(r"\b(?:hintergrund|background)\b", value, re.IGNORECASE)
            and re.search(
                r"\b(?:unscharf|dunkler|heller|blurry|blurred|darker|lighter)\b",
                value,
                re.IGNORECASE,
            )
        )
        or re.search(r"\b(?:andere|andre)\s+farb(?:e|en)\b", value, re.IGNORECASE)
    )


def _image_source_routing_context(request):
    if _file_context_is_image(request.file_context):
        return request.file_context
    if request.active_artifact_id:
        return {
            "kind": "image",
            "mime_type": "image/png",
            "artifact_id": request.active_artifact_id,
        }
    return request.file_context


def _looks_like_image_generation_request(prompt):
    value = str(prompt or "").strip()

    return bool(
        _IMAGE_NOUN_OF_PATTERN.search(value)
        or (
            _IMAGE_CREATION_VERB_PATTERN.search(value)
            and _IMAGE_NOUN_PATTERN.search(value)
        )
    )


@app.post("/api/chat/actions")
@observability.observed_turn
def run_chat_action(request: ChatActionRequest):

    routing_file_context = _image_source_routing_context(request)

    if request.action == "image_upscale":
        routing = {
            "intent": "image_upscale",
            "confidence": 1.0,
            "requires_tools": True,
            "reason": "Explicit image upscale action",
            "method": "explicit_image_upscale",
        }

    elif (
        _file_context_is_image(routing_file_context)
        and _looks_like_image_edit_request(request.prompt)
    ):
        routing = {
            "intent": "image_edit",
            "confidence": 1.0,
            "requires_tools": True,
            "reason": (
                "Image attachment with explicit "
                "image-edit instruction"
            ),
            "method": "deterministic_image_edit",
        }

    else:
        routing = classify_chat_action_details(
            request.prompt,
            routing_file_context,
            request.conversation_context,
        )

    action = routing["intent"]

    if (
        action in SEMANTIC_ROUTER_AGENT_INTENTS
        and not _semantic_agent_route_allowed(
            routing,
            request.prompt,
            routing_file_context,
            request.conversation_context,
        )
    ):
        routing = dict(routing)
        routing["original_intent"] = action
        routing["intent"] = "normal_chat"
        routing["agent_gate"] = "rejected"
        routing["agent_gate_reason"] = (
            "Semantischer Agent-Intent war nicht eindeutig genug."
        )
        action = "normal_chat"

    if action.startswith("file_"):
        return chat_tool_result(action, "requires_file_route", {"message": "Bestehende Datei-Pipeline verwenden"})
    if action == "normal_chat":
        return chat_tool_result(
            action,
            "not_applicable",
            {"routing": routing},
        )

    # No direct tool:
    # tell the frontend to start the agent loop automatically.
    if action in {
        "research_agent",
        "diagnostic_agent",
        "coding_agent",
        "orchestrator",
    }:
        return chat_tool_result(
            action,
            "completed",
            {
                "mode": action.removesuffix("_agent"),
                "automatic": True,
                "routing": routing,
            },
        )

    if action in {
        "image_generate",
        "image_edit",
        "image_upscale",
    }:
        try:
            job = _start_chat_image_job(action, request)
            return chat_tool_result(
                action,
                job.get("status", "queued"),
                {"job": job},
            )
        except HTTPException as exc:
            return chat_tool_result(action, "failed", error=str(exc.detail))
        except Exception as exc:
            return chat_tool_result(action, "failed", error=str(exc))

    handler = TOOLS.get(action)
    if not handler:
        return chat_tool_result(action, "failed", error="Aktion ist nicht registriert")
    try:
        data = handler(request)
        artifacts = []
        if action in {
            "image_generate",
            "image_edit",
            "image_upscale",
        }:
            artifact = data.get("image") if isinstance(data, dict) else None
            if artifact:
                artifacts.append(artifact)
        return chat_tool_result(action, "completed", data, artifacts=artifacts)
    except HTTPException as exc:
        return chat_tool_result(action, "failed", error=str(exc.detail))
    except Exception as exc:
        return chat_tool_result(action, "failed", error=str(exc))


# ============================================================
# Batch Transform Worker
# ============================================================


def invalid_json_error(analysis):
    error = (
        analysis.get("repair_error")
        or analysis.get("json_error")
        or {}
    )
    return (
        "JSON-Datei ist syntaktisch ungültig und konnte nicht "
        "automatisch repariert werden. Fehler in Zeile "
        f"{error.get('line', '?')}, Spalte {error.get('column', '?')}: "
        f"{error.get('message', 'Unbekannter JSON-Syntaxfehler')}"
    )



def sanitize_invalid_json_escapes(text):
    valid_simple = {
        '"',
        "\\",
        "/",
        "b",
        "f",
        "n",
        "r",
        "t",
    }

    out = []
    i = 0
    in_string = False

    while i < len(text):
        char = text[i]

        if char == '"':

            # Check whether the quote is escaped
            backslashes = 0
            j = i - 1

            while j >= 0 and text[j] == "\\":
                backslashes += 1
                j -= 1

            if backslashes % 2 == 0:
                in_string = not in_string

            out.append(char)
            i += 1
            continue

        if (
            in_string and
            char == "\\"
        ):
            if i + 1 >= len(text):
                out.append("\\\\")
                i += 1
                continue

            nxt = text[i + 1]

            # Valid simple JSON escape
            if nxt in valid_simple:
                out.append("\\")
                out.append(nxt)
                i += 2
                continue

            # A Unicode escape is valid only with exactly four hexadecimal digits
            if nxt == "u":
                hexpart = text[i + 2:i + 6]

                if (
                    len(hexpart) == 4 and
                    all(
                        c in "0123456789abcdefABCDEF"
                        for c in hexpart
                    )
                ):
                    out.append(
                        text[i:i + 6]
                    )
                    i += 6
                    continue

            # Preserve the literal backslash by escaping it. Removing it would
            # silently change values such as Windows paths.
            out.append("\\\\")
            out.append(nxt)
            i += 2
            continue

        out.append(char)
        i += 1

    return "".join(out)



def classify_batch_instruction(instruction):
    value = str(instruction or "").strip().lower()

    result = {
        "mode": "llm",
        "operations": [],
        "fast_operations": [],
        "llm_operations": [],
        "reason": "Keine sichere regelbasierte Transformation erkannt",
    }

    if not value:
        return result

    operations = []

    if (
        "email" in value
        or "e-mail" in value
    ):
        operations.append(
            "replace_emails"
        )

    if any(
        marker in value
        for marker in (
            "telefon",
            "rufnummer",
            "mobilnummer",
            "handynummer",
        )
    ):
        operations.append(
            "replace_phone_numbers"
        )

    if any(
        marker in value
        for marker in (
            "name",
            "vorname",
            "nachname",
        )
    ):
        operations.append(
            "replace_names"
        )

    address_markers = (
        "anschrift",
        "wohnadresse",
        "postadresse",
        "postalische adresse",
        "straße",
        "strasse",
        "hausnummer",
        "postleitzahl",
        " plz",
    )

    if any(
        marker in value
        for marker in address_markers
    ):
        operations.append(
            "replace_addresses"
        )

    broad_pii_request = (
        "personenbezogen" in value
        or "datenschutz" in value
        or "anonymisier" in value
    )

    if broad_pii_request:
        for operation in (
            "replace_emails",
            "replace_phone_numbers",
            "replace_names",
            "replace_addresses",
        ):
            if operation not in operations:
                operations.append(operation)

    fast_capable = {
        "replace_emails",
        "replace_phone_numbers",
    }

    fast_operations = [
        operation
        for operation in operations
        if operation in fast_capable
    ]

    llm_operations = [
        operation
        for operation in operations
        if operation not in fast_capable
    ]

    result["operations"] = operations
    result["fast_operations"] = fast_operations
    result["llm_operations"] = llm_operations

    has_fast = bool(fast_operations)
    has_llm = bool(llm_operations)

    if has_fast and not has_llm:
        result["mode"] = "fast"
        result["reason"] = (
            "Anweisung kann vollständig regelbasiert verarbeitet werden"
        )

    elif has_fast and has_llm:
        result["mode"] = "hybrid"
        result["reason"] = (
            "Ein Teil der Anweisung ist regelbasiert lösbar, "
            "der Rest benötigt semantische Verarbeitung"
        )

    elif has_llm:
        result["mode"] = "llm"
        result["reason"] = (
            "Anweisung benötigt semantische Verarbeitung"
        )

    return result

def apply_deterministic_transform(text, operations):
    value = str(text or "")

    operations = set(
        operations or []
    )

    if "replace_emails" in operations:
        value = re.sub(
            r'(?<![A-Za-z0-9._%+-])'
            r'[A-Za-z0-9._%+-]+'
            r'@[A-Za-z0-9.-]+'
            r'\.[A-Za-z]{2,}'
            r'(?![A-Za-z0-9.-])',
            '<EMAIL>',
            value,
            flags=re.IGNORECASE,
        )

    if "replace_phone_numbers" in operations:
        value = re.sub(
            r'(?<!\w)'
            r'(?:\+49|0049|0)'
            r'[\s()./-]*'
            r'(?:\d[\s()./-]*){6,14}'
            r'(?!\w)',
            '<TELEFON>',
            value,
        )

    # Deliberately avoid changing names and addresses heuristically
    # with regexes because the false-positive risk is too high.
    # These operations are handled later through the LLM fallback.

    return value


def hybrid_chunk_needs_llm(text, operations):
    """Conservative PII detector used after the safe FAST substitutions.

    False means that no requested semantic operation has a plausible target
    left.  The patterns intentionally err on the side of returning True.
    """
    value = str(text or "")
    requested = set(operations or [])
    if "replace_names" in requested:
        # Strong contextual indicators only.  A generic pair of capitalized
        # words caused too many false positives in ordinary German prose
        # ("Neue Kontaktanfrage", "Vielen Dank", product names, etc.).
        name_markers = (
            # Herr/Frau/Dr./Prof. + probable name.
            r"\b(?:Herr|Frau|Dr\.?|Prof\.?)\s+"
            r"[A-ZÄÖÜ][a-zäöüß-]{1,40}\b",

            # Explicit labels commonly used in forms, exports and JSON-ish
            # documents.
            r"(?<!\w)\"?(?:Name|name|Vorname|vorname|Nachname|"
            r"nachname|Ansprechpartner|Ansprechpartnerin)\"?"
            r"\s*[:=]\s*\"?"
            r"[A-ZÄÖÜ][a-zäöüß-]{1,40}"
            r"(?:\s+[A-ZÄÖÜ][a-zäöüß-]{1,40})?",

            # Greeting containing a full name.
            r"\b(?:Hallo|Guten Tag)\s+"
            r"[A-ZÄÖÜ][a-zäöüß-]{1,40}\s+"
            r"[A-ZÄÖÜ][a-zäöüß-]{1,40}\b",

            # Sign-off followed by a probable full name. Supports both real
            # newlines and escaped JSON newlines.
            r"\b(?:Mit freundlichen Grüßen|Beste Grüße|"
            r"Freundliche Grüße)\b"
            r"(?:\s|\\r|\\n){1,40}"
            r"[A-ZÄÖÜ][a-zäöüß-]{1,40}\s+"
            r"[A-ZÄÖÜ][a-zäöüß-]{1,40}\b",
        )

        if any(
            re.search(pattern, value)
            for pattern in name_markers
        ):
            return True
    if "replace_addresses" in requested:
        address_markers = (
            r"\b(?:straße|strasse|str\.|weg|platz|allee|gasse|ufer|ring)\s*\d+[a-zA-Z]?\b",
            r"\b\d{5}\s+[A-ZÄÖÜ][\wäöüß-]+\b",
        # An already anonymized value such as
        # "Address: <ADDRESS>" must not trigger the LLM fallback.
            r"\b(?:anschrift|adresse|postfach)\b"
            r"(?!\s*(?:lautet\s*)?(?:[:=]\s*)?"
            r"<(?:ADRESSE|PLZ|ORT)>)"
            r"\s*(?:lautet\s*)?(?:[:=]\s*)?"
            r"(?=[A-Za-zÄÖÜäöüß0-9])",
        )

        if any(
            re.search(pattern, value, re.IGNORECASE)
            for pattern in address_markers
        ):
            return True
    return False



def transform_structured_json_pii(value, operations):
    """Deterministically anonymize obvious PII in structured JSON fields.

    Returns:
        (transformed_value, changed_count)
    """
    requested = set(operations or [])
    changed = 0

    name_keys = {
        "name", "vorname", "nachname",
        "firstname", "lastname",
        "first_name", "last_name",
        "fullname", "full_name",
        "ansprechpartner", "ansprechpartnerin",
    }

    email_keys = {
        "email", "e-mail", "mail",
        "email_address", "emailadresse",
    }

    phone_keys = {
        "telefon", "telefonnummer",
        "phone", "phone_number",
        "mobile", "mobil", "mobilnummer",
        "handy", "handynummer",
        "rufnummer",
    }

    address_keys = {
        "adresse", "anschrift",
        "address", "street_address",
        "wohnadresse", "postadresse",
    }

    postal_keys = {
        "plz", "postcode", "postalcode",
        "postal_code", "zip", "zipcode",
        "zip_code",
    }

    city_keys = {
        "ort", "stadt", "city",
        "wohnort",
    }

    def normalize_key(key):
        return str(key or "").strip().lower().replace("-", "_")

    def walk(node):
        nonlocal changed

        if isinstance(node, list):
            return [walk(item) for item in node]

        if not isinstance(node, dict):
            return node

        result = {}

        for key, item in node.items():
            normalized = normalize_key(key)

            if isinstance(item, (dict, list)):
                result[key] = walk(item)
                continue

            if not isinstance(item, str):
                result[key] = item
                continue

            replacement = None

            if (
                "replace_names" in requested
                and normalized in name_keys
                and item.strip()
            ):
                replacement = "<NAME>"

            elif (
                "replace_emails" in requested
                and normalized in email_keys
                and item.strip()
            ):
                replacement = "<EMAIL>"

            elif (
                "replace_phone_numbers" in requested
                and normalized in phone_keys
                and item.strip()
            ):
                replacement = "<TELEFON>"

            elif (
                "replace_addresses" in requested
                and normalized in address_keys
                and item.strip()
            ):
                replacement = "<ADRESSE>"

            elif (
                "replace_addresses" in requested
                and normalized in postal_keys
                and item.strip()
            ):
                replacement = "<PLZ>"

            elif (
                "replace_addresses" in requested
                and normalized in city_keys
                and item.strip()
            ):
                replacement = "<ORT>"

            if replacement is not None:
                if item != replacement:
                    changed += 1
                result[key] = replacement
            else:
                result[key] = item

        return result

    return walk(value), changed



PII_FREETEXT_KEYS = {
    "body",
    "message",
    "text",
    "content",
    "description",
    "comment",
    "comments",
    "note",
    "notes",
    "subject",
}


def collect_json_freetext_targets(value):
    """Collect mutable paths for likely free-text JSON string fields."""
    targets = []

    def normalize_key(key):
        return str(key or "").strip().lower().replace("-", "_")

    def walk(node, path=()):
        if isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, path + (index,))
            return

        if not isinstance(node, dict):
            return

        for key, item in node.items():
            current_path = path + (key,)

            if isinstance(item, (dict, list)):
                walk(item, current_path)
                continue

            if (
                isinstance(item, str)
                and item.strip()
                and normalize_key(key) in PII_FREETEXT_KEYS
            ):
                targets.append({
                    "path": current_path,
                    "text": item,
                })

    walk(value)
    return targets


def set_json_path_value(value, path, replacement):
    """Set one nested dict/list value by a tuple path."""
    node = value

    for part in path[:-1]:
        node = node[part]

    node[path[-1]] = replacement



def apply_deterministic_freetext_pii(text, operations):
    """Replace only strong, explicit PII phrases in free text."""
    value = str(text or "")
    requested = set(operations or [])

    if "replace_names" in requested:
        value = re.sub(
            r"\b("
            r"(?:mein\s+Name\s+ist|Name\s*[:=])"
            r"\s+)"
            r"[A-ZÄÖÜ][a-zäöüß-]{1,40}"
            r"(?:\s+[A-ZÄÖÜ][a-zäöüß-]{1,40})?"
            r"(?:\s+\d+)?",
            r"\1<NAME>",
            value,
            flags=re.IGNORECASE,
        )

    if "replace_addresses" in requested:
        value = re.sub(
            r"\b("
            r"(?:meine\s+Anschrift\s+lautet|"
            r"Anschrift\s*[:=]|Adresse\s*[:=])"
            r"\s+)"
            r"[^.!?\n]{3,120}"
            r"(?=[.!?\n]|$)",
            r"\1<ADRESSE>",
            value,
            flags=re.IGNORECASE,
        )

    return value


def deterministic_pii_audit(text):
    """Report remaining obvious PII without modifying the completed output."""
    value = str(text or "")
    return {
        "emails": len(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value)),
        "phone_numbers": len(re.findall(r"(?<!\w)(?:\+49|0049|0)[\s()./-]*(?:\d[\s()./-]*){6,14}(?!\w)", value)),
        "addresses": len(re.findall(r"\b(?:straße|strasse|str\.|weg|platz|allee|gasse)\s*\d+[a-zA-Z]?\b", value, re.IGNORECASE)),
        "postal_places": len(re.findall(r"\b\d{5}\s+[A-ZÄÖÜ][\wäöüß-]+\b", value)),
    }


def analyze_input_file(input_path):
    path = Path(input_path)

    raw = path.read_bytes()

    result = {
        "path": str(path),
        "size_bytes": len(raw),
        "extension": path.suffix.lower(),
        "encoding": None,
        "bom": False,
        "detected_type": "text",
        "valid": True,
        "repairable": False,
        "repair": None,
        "chunk_strategy": "text",
        "estimated_input_tokens": 0,
        "recommended_chunk_tokens": BATCH_SINGLE_CHUNK_TOKENS,
        "notes": [],
    }

    # --------------------------------------------------------
    # Detect the encoding.
    # --------------------------------------------------------

    if raw.startswith(b"\xef\xbb\xbf"):
        result["encoding"] = "utf-8-sig"
        result["bom"] = True

    elif raw.startswith(b"\xff\xfe"):
        result["encoding"] = "utf-16-le"
        result["bom"] = True

    elif raw.startswith(b"\xfe\xff"):
        result["encoding"] = "utf-16-be"
        result["bom"] = True

    else:
        result["encoding"] = "utf-8"

    try:
        text = decode_batch_bytes(
            raw,
            result["encoding"],
            errors="strict",
        )

    except UnicodeDecodeError:
        text = decode_batch_bytes(
            raw,
            "utf-8",
            errors="replace",
        )

        result["encoding"] = "utf-8-replace"
        result["notes"].append(
            "Ungültige UTF-8-Zeichen wurden ersetzt"
        )

    result["estimated_input_tokens"] = estimate_batch_tokens(text)
    result["recommended_chunk_tokens"] = (
        recommended_batch_chunk_tokens(
            result["estimated_input_tokens"]
        )
    )

    stripped = text.lstrip()

    # --------------------------------------------------------
    # Detect JSON.
    # --------------------------------------------------------

    looks_like_json = (
        result["extension"] == ".json"
        or stripped.startswith("{")
        or stripped.startswith("[")
    )

    if looks_like_json:
        result["detected_type"] = "json"
        result["chunk_strategy"] = "json"

        try:
            data = json.loads(text)

            result["valid"] = True
            serialized = json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            )
            result["estimated_structured_tokens"] = (
                estimate_batch_tokens(serialized)
            )
            result["recommended_chunk_tokens"] = (
                recommended_batch_chunk_tokens(
                    max(
                        result["estimated_input_tokens"],
                        result["estimated_structured_tokens"],
                    )
                )
            )

            if isinstance(data, list):
                result["chunk_strategy"] = "json_array"

            elif isinstance(data, dict):
                list_keys = [
                    key
                    for key, value in data.items()
                    if isinstance(value, list)
                ]

                if list_keys:
                    largest_key = max(
                        list_keys,
                        key=lambda key: len(data[key]),
                    )

                    result["chunk_strategy"] = "json_object_list"
                    result["json_list_key"] = largest_key
                    result["json_list_items"] = len(
                        data[largest_key]
                    )

                else:
                    result["chunk_strategy"] = "json_object"

            return result

        except json.JSONDecodeError as exc:
            result["valid"] = False
            result["json_error"] = {
                "message": exc.msg,
                "line": exc.lineno,
                "column": exc.colno,
                "position": exc.pos,
            }

            # Repair invalid JSON escapes using the safe general rule.
            repaired = sanitize_invalid_json_escapes(text)

            if repaired != text:
                try:
                    data = json.loads(repaired)

                    result["repairable"] = True
                    result["repair"] = "sanitize_invalid_json_escapes"
                    result["estimated_structured_tokens"] = (
                        estimate_batch_tokens(
                            json.dumps(
                                data,
                                ensure_ascii=False,
                                indent=2,
                            )
                        )
                    )
                    result["recommended_chunk_tokens"] = (
                        recommended_batch_chunk_tokens(
                            max(
                                result["estimated_input_tokens"],
                                result["estimated_structured_tokens"],
                            )
                        )
                    )
                    result["notes"].append(
                        "Ungültige JSON-Escapes können "
                        "automatisch repariert werden"
                    )

                    if isinstance(data, list):
                        result["chunk_strategy"] = "json_array"

                    elif isinstance(data, dict):
                        list_keys = [
                            key
                            for key, value in data.items()
                            if isinstance(value, list)
                        ]

                        if list_keys:
                            largest_key = max(
                                list_keys,
                                key=lambda key: len(data[key]),
                            )

                            result["chunk_strategy"] = "json_object_list"
                            result["json_list_key"] = largest_key
                            result["json_list_items"] = len(
                                data[largest_key]
                            )

                        else:
                            result["chunk_strategy"] = "json_object"

                    return result

                except json.JSONDecodeError as repair_exc:
                    result["repair_error"] = {
                        "message": repair_exc.msg,
                        "line": repair_exc.lineno,
                        "column": repair_exc.colno,
                        "position": repair_exc.pos,
                    }

            result["chunk_strategy"] = "json_invalid"
            result["notes"].append(
                "JSON ungültig und nicht sicher reparierbar; "
                "Verarbeitung wird vor dem ersten MLX-Aufruf beendet"
            )

            return result

    # --------------------------------------------------------
    # Detect SQL.
    # --------------------------------------------------------

    upper = stripped[:4000].upper()

    sql_markers = (
        "INSERT INTO",
        "UPDATE ",
        "DELETE FROM",
        "CREATE TABLE",
        "ALTER TABLE",
        "SELECT ",
        "DROP TABLE",
        "TRUNCATE TABLE",
    )

    if (
        result["extension"] == ".sql"
        or any(marker in upper for marker in sql_markers)
    ):
        result["detected_type"] = "sql"
        result["chunk_strategy"] = "sql_statements"
        return result

    # --------------------------------------------------------
    # Detect CSV.
    # --------------------------------------------------------

    lines = text.splitlines()

    if result["extension"] == ".csv":
        result["detected_type"] = "csv"
        result["chunk_strategy"] = "csv_rows"
        return result

    if lines:
        first = lines[0]

        separators = {
            ",": first.count(","),
            ";": first.count(";"),
            "\t": first.count("\t"),
        }

        separator, count = max(
            separators.items(),
            key=lambda item: item[1],
        )

        if count >= 2:
            result["detected_type"] = "csv"
            result["chunk_strategy"] = "csv_rows"
            result["csv_separator"] = separator
            return result

    # --------------------------------------------------------
    # Other structured text files.
    # --------------------------------------------------------

    extension_map = {
        ".txt": "text",
        ".md": "text",
        ".log": "text",
        ".xml": "text",
        ".yml": "text",
        ".yaml": "text",
        ".php": "text",
        ".js": "text",
        ".ts": "text",
        ".py": "text",
        ".html": "text",
        ".css": "text",
        ".ini": "text",
        ".conf": "text",
    }

    if result["extension"] in extension_map:
        result["detected_type"] = extension_map[
            result["extension"]
        ]

    result["chunk_strategy"] = "text"
    return result


def analyze_file_structure(input_path):
    """Read bounded, deterministic file facts; never sends file text to an LLM."""
    path = Path(input_path)
    base = analyze_input_file(path)
    raw = path.read_bytes()
    encoding = base.get("encoding", "utf-8")
    try:
        text = decode_batch_bytes(
            raw,
            encoding,
            errors="replace",
        )
    except LookupError:
        text = decode_batch_bytes(raw, "utf-8", errors="replace")
    lines = text.splitlines()
    result = dict(base)
    result.update({
        "filename": path.name,
        "estimated_tokens": max(1, estimate_batch_tokens(text)),
        "line_count": len(lines),
        "sample": text[:FILE_SAMPLE_MAX_CHARS],
    })
    detected = result.get("detected_type")
    if detected == "json" and result.get("valid"):
        data = json.loads(text)
        result["json_top_level"] = type(data).__name__
        records = data if isinstance(data, list) else next((v for v in data.values() if isinstance(v, list)), [])
        result["record_count"] = len(records) if isinstance(records, list) else None
        if isinstance(data, dict): result["object_keys"] = list(data.keys())[:100]
        if isinstance(records, list) and records:
            objects = [item for item in records[:200] if isinstance(item, dict)]
            keys = {}
            for item in objects:
                for key in item: keys[key] = keys.get(key, 0) + 1
            result["frequent_keys"] = [key for key, _ in sorted(keys.items(), key=lambda item: -item[1])[:50]]
            result["sample_structure"] = objects[:3]
            date_values = []
            for item in objects:
                for key, value in item.items():
                    if isinstance(value, str) and any(marker in key.lower() for marker in ("date", "datum", "zeit", "time")):
                        date_values.append(value)
            if date_values:
                result["date_fields"] = sorted(set(date_values))[:10]
                result["date_range_sample"] = {"min": min(date_values), "max": max(date_values)}
    elif detected == "csv":
        import csv
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|") if text.strip() else csv.excel
        reader = csv.reader(lines, dialect)
        rows = list(reader)
        result["delimiter"] = dialect.delimiter
        result["columns"] = rows[0] if rows else []
        result["record_count"] = max(0, len(rows) - 1)
        result["sample_rows"] = rows[1:4]
    elif detected == "sql":
        statements = re.findall(r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|SELECT)\b", text, re.IGNORECASE)
        result["statement_types"] = {key.upper(): statements.count(key) for key in set(statements)}
        result["tables"] = sorted(set(re.findall(r"\b(?:INTO|UPDATE|TABLE|FROM)\s+[`\"]?([\w.]+)", text, re.IGNORECASE)))[:100]
        result["statement_count"] = len(statements)
    else:
        result["paragraph_count"] = len([part for part in re.split(r"\n\s*\n", text) if part.strip()])
        result["headings"] = [line.lstrip("# ").strip() for line in lines if line.startswith("#")][:50]
    return result



FILE_EXCERPT_MAX_LINES = 500
FILE_EXCERPT_MAX_CHARS = 40000
FILE_EXCERPT_MAX_CHARS_PER_LINE = 8000


def parse_file_excerpt_selection(instruction):
    """
    Detect an explicitly requested line range.

    Returned line numbers are 1-based and inclusive.
    The actual end for ``last_lines`` is resolved against the file later.
    """
    value = str(instruction or "").strip().lower()

    if not value:
        return None

    # Examples:
    #   lines 100-150
    #   lines 100 to 150
    #   lines 100 through 150
    range_match = re.search(
        r"\b(?:zeile|zeilen|lines?)\s+"
        r"(\d+)\s*(?:-|–|—|bis|to|through)\s*(\d+)\b",
        value,
        re.IGNORECASE,
    )

    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))

        if start < 1 or end < start:
            return None

        if end - start + 1 > FILE_EXCERPT_MAX_LINES:
            end = start + FILE_EXCERPT_MAX_LINES - 1

        return {
            "kind": "line_range",
            "start_line": start,
            "end_line": end,
        }

    # Examples:
    #   German singular variant for "first 20 lines"
    #   German plural variant for "first 20 lines"
    #   first 20 lines
    first_match = re.search(
        r"\b(?:erste[nrms]?|first)\s+(\d+)\s+"
        r"(?:zeile|zeilen|lines?)\b",
        value,
        re.IGNORECASE,
    )

    if first_match:
        count = min(
            int(first_match.group(1)),
            FILE_EXCERPT_MAX_LINES,
        )

        if count < 1:
            return None

        return {
            "kind": "line_range",
            "start_line": 1,
            "end_line": count,
        }

    # Examples:
    #   last 30 lines (German singular form)
    #   last 30 lines (German plural form)
    #   last 30 lines
    last_match = re.search(
        r"\b(?:letzte[nrms]?|last)\s+(\d+)\s+"
        r"(?:zeile|zeilen|lines?)\b",
        value,
        re.IGNORECASE,
    )

    if last_match:
        count = min(
            int(last_match.group(1)),
            FILE_EXCERPT_MAX_LINES,
        )

        if count < 1:
            return None

        return {
            "kind": "last_lines",
            "count": count,
        }

    return None


def create_file_analysis_job(input_path, instruction, file_type, chunk_tokens, operation, attachment_id=None, trace_id=None):
    path = Path(input_path).expanduser()
    if not path.is_file(): raise HTTPException(status_code=404, detail="Eingabedatei nicht gefunden")
    job_id = uuid.uuid4().hex[:12]
    selection = parse_file_excerpt_selection(instruction)
    job = {
        "id": job_id, "kind": "file_analysis", "operation": operation,
        "trace_id": observability.ensure_trace_id(trace_id),
        "attachment_id": attachment_id, "input_path": str(path), "instruction": instruction,
        "file_type": file_type, "chunk_tokens": max(500, min(int(chunk_tokens), 20000)),
        "selection": selection,
        "status": "queued", "created_at": time.time(), "started_at": None, "finished_at": None,
        "processed_chunks": 0, "total_chunks": None, "error": None, "mlx_calls": 0,
    }
    with BATCH_LOCK:
        jobs = load_batch_jobs(); jobs[job_id] = job; save_batch_jobs(jobs)
    return job




# ---------------------------------------------------------
# Shared MLX runtime manager
# ---------------------------------------------------------

def wait_for_model_runtime(alias: str, timeout: int = 180):
    """
    Wait until the selected model is both configured as active
    and the OpenAI-compatible MLX endpoint responds.
    """
    models = load_models()

    selected = next(
        (
            item
            for item in models
            if item.get("alias") == alias
        ),
        None,
    )

    if selected is None:
        raise RuntimeError(
            f"Unbekanntes Modell-Alias: {alias}"
        )

    expected_repo = selected.get("repo")
    deadline = time.monotonic() + timeout
    last_error = None

    while time.monotonic() < deadline:
        try:
            config = load_config()

            current_repo = config.get("MODEL")
            port = int(config.get("PORT", 8000))

            if current_repo != expected_repo:
                time.sleep(0.5)
                continue

            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/models",
                method="GET",
            )

            with urllib.request.urlopen(
                request,
                timeout=5,
            ) as response:
                if 200 <= response.status < 500:
                    return {
                        "ok": True,
                        "alias": alias,
                        "repo": expected_repo,
                        "port": port,
                    }

        except Exception as exc:
            last_error = str(exc)

        time.sleep(1)

    detail = (
        f"MLX-Modell '{alias}' wurde nicht "
        f"innerhalb von {timeout}s bereit"
    )

    if last_error:
        detail += f": {last_error}"

    raise RuntimeError(detail)


def switch_model_runtime(alias: str):
    """
    Switch the single shared MLX runtime to an alias.

    Caller must hold MODEL_RUNTIME_LOCK.
    """
    models = load_models()

    known_aliases = {
        item.get("alias")
        for item in models
    }

    if alias not in known_aliases:
        raise RuntimeError(
            f"Unbekanntes Modell-Alias: {alias}"
        )

    selected = next(item for item in models if item.get("alias") == alias)
    validate_model_reference(selected.get("repo", ""))

    try:
        result = subprocess.run(
            [str(MLX), "model", alias],
            capture_output=True,
            text=True,
            timeout=300,
        )

    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Modellwechsel Timeout: {alias}"
        ) from exc

    if result.returncode != 0:
        raise RuntimeError(
            "Modellwechsel fehlgeschlagen: "
            f"{alias}\n"
            f"stdout: {result.stdout.strip()}\n"
            f"stderr: {result.stderr.strip()}"
        )

    ready = wait_for_model_runtime(
        alias,
        timeout=180,
    )

    return {
        "ok": True,
        "alias": alias,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "runtime": ready,
    }


@app.post("/api/runtime/ensure-role/{role}")
def ensure_runtime_role(role: str):
    if role not in MODEL_ROLE_NAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Unbekannte Modellrolle: {role}",
        )

    try:
        result = ensure_model_for_role(role)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    return result


def ensure_model_for_role(role: str):
    """
    Ensure that the model configured for a logical role
    is loaded in the shared MLX runtime.
    """
    with MODEL_RUNTIME_LOCK:
        resolved = resolve_model_role(role)

        if resolved.get("available") is False:
            raise RuntimeError(
                "Das für die Rolle "
                f"'{role}' konfigurierte Modell "
                f"'{resolved.get('alias')}' "
                "ist nicht verfügbar"
            )

        if not resolved.get("repo"):
            raise RuntimeError(
                f"Für die Rolle '{role}' "
                "konnte kein Modell aufgelöst werden"
            )

        if not resolved.get("requires_switch"):
            return {
                "ok": True,
                "role": role,
                "switched": False,
                "resolved": resolved,
            }

        alias = resolved.get("alias")

        if not alias:
            raise RuntimeError(
                f"Für die Rolle '{role}' "
                "fehlt ein Modell-Alias"
            )

        switch_result = switch_model_runtime(alias)

        resolved = resolve_model_role(role)

        if resolved.get("requires_switch"):
            raise RuntimeError(
                "Modellwechsel wurde ausgeführt, "
                f"aber Rolle '{role}' ist weiterhin "
                "nicht aktiv"
            )

        return {
            "ok": True,
            "role": role,
            "switched": True,
            "resolved": resolved,
            "switch": switch_result,
        }



ROUTER_MODEL = os.environ.get(
    "MLX_ROUTER_MODEL_PATH",
    str(Path.home() / "Models/router/Qwen3.5-0.8B-MLX-4bit"),
)
ROUTER_URL = "http://127.0.0.1:8040"


def router_llm(messages, max_tokens=220, temperature=0.0):
    """
    Dedicated semantic router.

    Runs independently of the switchable main runtime on port 8000, so
    intent classification does not trigger a model switch.
    """
    payload = {
        "model": ROUTER_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {
            "enable_thinking": False,
        },
    }

    request = urllib.request.Request(
        f"{ROUTER_URL}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )
    call_metrics = observability.ModelCallMetrics(
        purpose="router.classify",
        model=ROUTER_MODEL,
        role="router",
        backend="mlx_vlm",
        messages=messages,
        context_sources=observability.message_context_counts(messages),
    )

    try:
        connect_started = time.monotonic()
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            call_metrics.set_upstream_connect(
                (time.monotonic() - connect_started) * 1000
            )
            result = json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as exc:
        call_metrics.fail("http_error")
        body = exc.read().decode(
            "utf-8",
            errors="replace",
        )
        raise RuntimeError(
            f"Router-LLM HTTP {exc.code}: {body}"
        ) from exc

    except urllib.error.URLError as exc:
        call_metrics.fail(type(exc).__name__)
        raise RuntimeError(
            "Router-LLM nicht erreichbar: "
            f"{exc.reason}"
        ) from exc

    except Exception as exc:
        call_metrics.fail(type(exc).__name__)
        raise

    try:
        choice = result["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError):
        call_metrics.fail("invalid_response")
        raise

    output = (
        message.get("content")
        or message.get("reasoning")
        or ""
    ).strip()
    call_metrics.finish(
        usage=result.get("usage"),
        output_text=output,
        finish_reason=choice.get("finish_reason"),
    )
    return output


def agent_llm(messages, max_tokens=1200, temperature=0.1):
    """
    Direct MLX call for the autonomous agent loop.

    Hold the runtime lock throughout the model switch and the LLM request.
    """
    call_metrics = observability.ModelCallMetrics(
        purpose=observability.current_call_purpose("agent.call"),
        role="agent",
        messages=messages,
        context_sources=observability.current_context_sources(
            observability.message_context_counts(
                messages,
                "tool_agent",
            )
        ),
    )
    wait_started = time.monotonic()
    with MODEL_RUNTIME_LOCK:
        queue_wait_ms = (time.monotonic() - wait_started) * 1000
        call_metrics.set_queue_wait(queue_wait_ms)
        try:
            runtime = ensure_model_for_role("agent")
            role = runtime["resolved"]
            model = role.get("repo")
        except Exception as exc:
            call_metrics.fail(type(exc).__name__)
            raise

        if not model:
            call_metrics.fail("model_unavailable")
            raise RuntimeError(
                "Für die Agent-Rolle ist kein verfügbares "
                "MLX-Modell konfiguriert"
            )

        call_metrics.set_model(
            model=model,
            role="agent",
            alias=role.get("alias"),
            backend=role.get("backend"),
        )

        # Reload the configuration after a possible model switch.
        try:
            config = load_config()
            port = int(config.get("PORT", 8000))
        except Exception as exc:
            call_metrics.fail(type(exc).__name__)
            raise

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {
                "enable_thinking": False,
            },
        }

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            connect_started = time.monotonic()
            with urllib.request.urlopen(
                request,
                timeout=900,
            ) as response:
                call_metrics.set_upstream_connect(
                    (time.monotonic() - connect_started) * 1000
                )
                result = json.loads(
                    response.read().decode("utf-8")
                )

        except urllib.error.HTTPError as exc:
            call_metrics.fail("http_error")
            body = exc.read().decode(
                "utf-8",
                errors="replace",
            )
            raise RuntimeError(
                f"Agent-LLM HTTP {exc.code}: {body}"
            ) from exc

        except urllib.error.URLError as exc:
            call_metrics.fail(type(exc).__name__)
            raise RuntimeError(
                "Agent-LLM nicht erreichbar: "
                f"{exc.reason}"
            ) from exc

        except Exception as exc:
            call_metrics.fail(type(exc).__name__)
            raise

        try:
            choice = result["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError):
            call_metrics.fail("invalid_response")
            raise

        output = (
            message.get("content")
            or message.get("reasoning")
            or ""
        ).strip()
        call_metrics.finish(
            usage=result.get("usage"),
            output_text=output,
            finish_reason=choice.get("finish_reason"),
        )
        return output


def observed_agent_llm(
    purpose,
    messages,
    max_tokens=1200,
    temperature=0.1,
):
    """Call the agent model with a safe purpose label for metrics."""
    with observability.model_call_context(purpose):
        return agent_llm(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )




# ---------------------------------------------------------
# Role-aware Chat Gateway
# ---------------------------------------------------------

class RuntimeChatRequest(BaseModel):
    messages: list[dict]
    temperature: float = 0.7
    max_tokens: int = 3000
    stream: bool = True
    trace_id: str | None = None
    context_sources: dict | None = None


@app.post("/api/runtime/chat")
def runtime_chat(request: RuntimeChatRequest):
    """
    Central role-aware MLX access for regular chat.

    Hold the runtime lock from the model switch until the MLX response
    finishes completely.
    """

    trace_id = observability.ensure_trace_id(request.trace_id)
    call_metrics = observability.ModelCallMetrics(
        trace_id=trace_id,
        purpose="chat.runtime",
        role="chat",
        messages=request.messages,
        context_sources=request.context_sources,
    )
    wait_started = time.monotonic()

    with MODEL_RUNTIME_LOCK:
        call_metrics.set_queue_wait(
            (time.monotonic() - wait_started) * 1000
        )

        try:
            runtime = ensure_model_for_role("chat")
            role = runtime["resolved"]
            model = role.get("repo")
        except Exception as exc:
            call_metrics.fail(type(exc).__name__)
            raise

        if not model:
            call_metrics.fail("model_unavailable")
            raise HTTPException(
                status_code=500,
                detail=(
                    "Für die Chat-Rolle ist kein "
                    "MLX-Modell verfügbar"
                ),
            )

        call_metrics.set_model(
            model=model,
            role="chat",
            alias=role.get("alias"),
            backend=role.get("backend"),
        )

        try:
            config = load_config()
            port = int(config.get("PORT", 8000))
        except Exception as exc:
            call_metrics.fail(type(exc).__name__)
            raise

        payload = {
            "model": model,
            "messages": request.messages,
            "temperature": max(
                0.0,
                min(float(request.temperature), 2.0),
            ),
            "max_tokens": max(
                1,
                min(int(request.max_tokens), 32000),
            ),
            "stream": bool(request.stream),
        }

        upstream = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            connect_started = time.monotonic()
            with urllib.request.urlopen(
                upstream,
                timeout=900,
            ) as response:
                call_metrics.set_upstream_connect(
                    (time.monotonic() - connect_started) * 1000
                )

                content_type = (
                    response.headers.get(
                        "Content-Type",
                        "application/json",
                    )
                )

                body = response.read()

                try:
                    result = json.loads(body.decode("utf-8"))
                    choices = result.get("choices")
                    choice = (
                        choices[0]
                        if isinstance(choices, list) and choices
                        else {}
                    )
                    message = choice.get("message", {})
                    call_metrics.finish(
                        usage=result.get("usage"),
                        output_text=(
                            message.get("content")
                            or message.get("reasoning")
                            or ""
                        ),
                        finish_reason=choice.get("finish_reason"),
                    )
                except (UnicodeDecodeError, json.JSONDecodeError):
                    call_metrics.finish()

                return Response(
                    content=body,
                    status_code=response.status,
                    media_type=content_type.split(";")[0],
                )

        except urllib.error.HTTPError as exc:
            call_metrics.fail("http_error")
            body = exc.read().decode(
                "utf-8",
                errors="replace",
            )

            raise HTTPException(
                status_code=exc.code,
                detail=body,
            ) from exc

        except urllib.error.URLError as exc:
            call_metrics.fail(type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail=(
                    "MLX-Runtime nicht erreichbar: "
                    f"{exc.reason}"
                ),
            ) from exc

        except Exception as exc:
            call_metrics.fail(type(exc).__name__)
            raise



@app.post("/api/runtime/chat/stream")
def runtime_chat_stream(request: RuntimeChatRequest):
    """
    Role-aware streaming gateway for regular chat.

    The actual MLX stream runs in a dedicated worker thread. This ensures
    MODEL_RUNTIME_LOCK is always acquired and released in the same thread.

    The HTTP generator itself does not hold a runtime lock.
    """

    trace_id = observability.ensure_trace_id(request.trace_id)
    event_queue = queue.Queue()
    sentinel = object()

    def put_error(message):
        event = json.dumps(
            {
                "error": str(message),
            },
            ensure_ascii=False,
        )
        event_queue.put(
            "event: error\n"
            f"data: {event}\n\n"
        )

    def worker():
        call_metrics = observability.ModelCallMetrics(
            trace_id=trace_id,
            purpose="chat.stream",
            role="chat",
            messages=request.messages,
            context_sources=request.context_sources,
        )
        output_characters = 0
        reasoning_characters = 0
        usage = None
        finish_reason = None
        wait_started = time.monotonic()

        def put_metrics():
            event_queue.put(
                observability.metrics_sse(trace_id)
            )

        try:
            with MODEL_RUNTIME_LOCK:
                call_metrics.set_queue_wait(
                    (time.monotonic() - wait_started) * 1000
                )
                runtime = ensure_model_for_role("chat")
                role = runtime["resolved"]
                model = role.get("repo")

                if not model:
                    call_metrics.fail("model_unavailable")
                    put_metrics()
                    put_error(
                        "Für die Chat-Rolle ist kein "
                        "MLX-Modell verfügbar"
                    )
                    return

                call_metrics.set_model(
                    model=model,
                    role="chat",
                    alias=role.get("alias"),
                    backend=role.get("backend"),
                )

                config = load_config()
                port = int(config.get("PORT", 8000))

                payload = {
                    "model": model,
                    "messages": request.messages,
                    "temperature": max(
                        0.0,
                        min(
                            float(request.temperature),
                            2.0,
                        ),
                    ),
                    "max_tokens": max(
                        1,
                        min(
                            int(request.max_tokens),
                            32000,
                        ),
                    ),
                    "stream": True,
                }

                upstream = urllib.request.Request(
                    (
                        f"http://127.0.0.1:{port}"
                        "/v1/chat/completions"
                    ),
                    data=json.dumps(
                        payload
                    ).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )

                try:
                    connect_started = time.monotonic()
                    with urllib.request.urlopen(
                        upstream,
                        timeout=900,
                    ) as response:
                        call_metrics.set_upstream_connect(
                            (time.monotonic() - connect_started) * 1000
                        )

                        for raw_line in response:
                            line = raw_line.decode(
                                "utf-8",
                                errors="replace",
                            ).strip()

                            if not line:
                                continue

                            if not line.startswith("data:"):
                                continue

                            data = line[5:].strip()

                            if data == "[DONE]":
                                break

                            try:
                                obj = json.loads(data)
                            except json.JSONDecodeError:
                                continue

                            if isinstance(obj.get("usage"), dict):
                                usage = obj["usage"]

                            try:
                                choice = obj["choices"][0]
                            except (
                                KeyError,
                                IndexError,
                                TypeError,
                            ):
                                continue

                            delta = (
                                choice.get("delta")
                                or {}
                            )
                            if choice.get("finish_reason") is not None:
                                finish_reason = choice.get("finish_reason")

                            reasoning = (
                                delta.get("reasoning")
                                or delta.get(
                                    "reasoning_content"
                                )
                                or ""
                            )

                            content = (
                                delta.get("content")
                                or ""
                            )

                            if reasoning:
                                call_metrics.mark_first_token()
                                reasoning_characters += len(reasoning)
                                event = json.dumps(
                                    {
                                        "type": "reasoning",
                                        "text": reasoning,
                                    },
                                    ensure_ascii=False,
                                )
                                event_queue.put(
                                    f"data: {event}\n\n"
                                )

                            if content:
                                call_metrics.mark_first_token()
                                output_characters += len(content)
                                event = json.dumps(
                                    {
                                        "type": "content",
                                        "text": content,
                                    },
                                    ensure_ascii=False,
                                )
                                event_queue.put(
                                    f"data: {event}\n\n"
                                )

                        call_metrics.finish(
                            usage=usage,
                            output_characters=output_characters,
                            reasoning_characters=reasoning_characters,
                            finish_reason=finish_reason,
                        )
                        put_metrics()
                        event_queue.put(
                            "event: done\n"
                            "data: {}\n\n"
                        )

                except urllib.error.HTTPError as exc:
                    call_metrics.fail("http_error")
                    body = exc.read().decode(
                        "utf-8",
                        errors="replace",
                    )
                    put_metrics()
                    put_error(
                        f"HTTP {exc.code}: {body}"
                    )

                except urllib.error.URLError as exc:
                    call_metrics.fail(type(exc).__name__)
                    put_metrics()
                    put_error(
                        "MLX-Runtime nicht erreichbar: "
                        f"{exc.reason}"
                    )

                except Exception as exc:
                    call_metrics.fail(type(exc).__name__)
                    put_metrics()
                    put_error(exc)

        except Exception as exc:
            if call_metrics.metric["status"] == "running":
                call_metrics.fail(type(exc).__name__)
                put_metrics()
            put_error(exc)

        finally:
            event_queue.put(sentinel)

    thread = threading.Thread(
        target=worker,
        name="mlx-chat-stream",
        daemon=True,
    )
    thread.start()

    def generate():
        while True:
            item = event_queue.get()

            if item is sentinel:
                break

            yield item

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


SHELL_READ_COMMANDS = {
    # Prozesse / System
    "ps",
    "pgrep",
    "df",
    "du",
    "uptime",
    "vm_stat",
    "memory_pressure",
    "sysctl",
    "lsof",
    "sw_vers",
    "uname",

    # Files and programs
    "ls",
    "find",
    "mdfind",
    "stat",
    "file",
    "which",
    "whereis",

    # macOS
    "system_profiler",
    "launchctl",

# Package management: read-only access
    "brew",

    # Netzwerk / Docker
    "curl",
    "docker",
}


SHELL_READ_DOCKER_SUBCOMMANDS = {
    "ps",
    "logs",
    "inspect",
    "stats",
    "images",
    "volume",
    "network",
    "info",
    "version",
}


SHELL_READ_BREW_SUBCOMMANDS = {
    "list",
    "info",
    "leaves",
    "outdated",
    "deps",
    "uses",
    "config",
    "doctor",
    "--version",
}


SHELL_READ_MAX_OUTPUT = 30_000


def validate_shell_read_command(command):
    """Validate a diagnostic command without a shell interpreter."""

    import shlex

    command = str(command or "").strip()

    if not command:
        raise ValueError("Leerer Diagnosebefehl")

    if len(command) > 2000:
        raise ValueError("Diagnosebefehl ist zu lang")

    try:
        args = shlex.split(command)
    except ValueError as exc:
        raise ValueError(
            f"Ungültiger Diagnosebefehl: {exc}"
        ) from exc

    if not args:
        raise ValueError("Leerer Diagnosebefehl")

    executable = args[0]

    # The executable itself must not be selected through an
    # arbitrary path.
    if "/" in executable:
        raise ValueError(
            "Absolute oder relative Programmpfade sind nicht erlaubt"
        )

    if executable not in SHELL_READ_COMMANDS:
        raise ValueError(
            f"Befehl nicht für shell_read freigegeben: {executable}"
        )


    # ========================================================
    # sysctl
    # ========================================================

    if executable == "sysctl":

            # sysctl -w changes kernel parameters.
        for arg in args[1:]:
            if arg == "-w" or arg.startswith("-w"):
                raise ValueError(
                    "sysctl-Schreibzugriff ist nicht erlaubt"
                )

            if "=" in arg and not arg.startswith("-"):
                raise ValueError(
                    "sysctl-Wertzuweisungen sind nicht erlaubt"
                )


    # ========================================================
    # find
    # ========================================================

    if executable == "find":

        blocked_find_actions = {
            "-delete",
            "-exec",
            "-execdir",
            "-ok",
            "-okdir",
            "-fprint",
            "-fprint0",
            "-fprintf",
            "-fls",
        }

        for arg in args[1:]:

            lowered = arg.lower()

            if lowered in blocked_find_actions:
                raise ValueError(
                    f"find-Aktion nicht erlaubt: {arg}"
                )

            # Guard against variants such as -execdir.
            if (
                lowered.startswith("-exec")
                or lowered.startswith("-ok")
                or lowered.startswith("-fprint")
            ):
                raise ValueError(
                    f"find-Aktion nicht erlaubt: {arg}"
                )


    # ========================================================
    # brew
    # ========================================================

    if executable == "brew":

        if len(args) < 2:
            raise ValueError(
                "Homebrew-Unterbefehl fehlt"
            )

        subcommand = args[1]

        if subcommand not in SHELL_READ_BREW_SUBCOMMANDS:
            raise ValueError(
                "Homebrew-Unterbefehl nicht für shell_read "
                f"freigegeben: {subcommand}"
            )

            # Additional guard against known write options.
        blocked_brew_options = {
            "--force",
            "--overwrite",
        }

        for arg in args[2:]:
            if arg in blocked_brew_options:
                raise ValueError(
                    f"Homebrew-Option nicht erlaubt: {arg}"
                )


    # ========================================================
    # launchctl
    # ========================================================

    if executable == "launchctl":

        # Allow read-only queries only.
        if len(args) < 2:
            raise ValueError(
                "launchctl-Unterbefehl fehlt"
            )

        allowed_launchctl = {
            "list",
            "print",
            "print-disabled",
        }

        if args[1] not in allowed_launchctl:
            raise ValueError(
                "launchctl-Unterbefehl nicht erlaubt: "
                f"{args[1]}"
            )


    # ========================================================
    # Docker
    # ========================================================

    if executable == "docker":

        if len(args) < 2:
            raise ValueError(
                "Docker-Unterbefehl fehlt"
            )

        subcommand = args[1]

        if subcommand not in SHELL_READ_DOCKER_SUBCOMMANDS:
            raise ValueError(
                "Docker-Unterbefehl nicht für shell_read "
                f"freigegeben: {subcommand}"
            )

            # Restrict volume and network subcommands as well.
        if subcommand in {"volume", "network"}:

            if len(args) < 3:
                raise ValueError(
                    f"docker {subcommand}: Unterbefehl fehlt"
                )

            allowed_nested = {
                "ls",
                "inspect",
            }

            if args[2] not in allowed_nested:
                raise ValueError(
                    f"docker {subcommand} {args[2]} "
                    "ist nicht für shell_read freigegeben"
                )


    # ========================================================
    # curl
    # ========================================================

    if executable == "curl":

        blocked_curl_options = {
            "-d",
            "--data",
            "--data-raw",
            "--data-binary",
            "--data-urlencode",
            "-F",
            "--form",
            "-T",
            "--upload-file",
            "-X",
            "--request",
            "-o",
            "--output",
            "-O",
            "--remote-name",
            "--config",
        }

        blocked_prefixes = (
            "--data=",
            "--data-raw=",
            "--data-binary=",
            "--data-urlencode=",
            "--form=",
            "--upload-file=",
            "--request=",
            "--output=",
            "--config=",
        )

        for arg in args[1:]:

            if arg in blocked_curl_options:
                raise ValueError(
                    f"curl-Option nicht erlaubt: {arg}"
                )

            if arg.startswith(blocked_prefixes):
                raise ValueError(
                    f"curl-Option nicht erlaubt: {arg}"
                )


    return args


def tool_shell_read(command):
    """
    Execute only approved read-only diagnostic commands.

    Do not use shell=True, pipes, redirects, or command substitution.
    """
    args = validate_shell_read_command(command)

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=20,
            stdin=subprocess.DEVNULL,
        )

    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""

        if isinstance(stdout, bytes):
            stdout = stdout.decode(
                "utf-8",
                errors="replace",
            )

        if isinstance(stderr, bytes):
            stderr = stderr.decode(
                "utf-8",
                errors="replace",
            )

        return {
            "command": command,
            "status": "timeout",
            "stdout": stdout[-SHELL_READ_MAX_OUTPUT:],
            "stderr": stderr[-SHELL_READ_MAX_OUTPUT:],
        }

    except FileNotFoundError:
        raise ValueError(
            f"Programm nicht gefunden: {args[0]}"
        )

    stdout = result.stdout or ""
    stderr = result.stderr or ""

    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": stdout[-SHELL_READ_MAX_OUTPUT:],
        "stderr": stderr[-SHELL_READ_MAX_OUTPUT:],
        "truncated": (
            len(stdout) > SHELL_READ_MAX_OUTPUT
            or len(stderr) > SHELL_READ_MAX_OUTPUT
        ),
    }


def tool_process_usage(limit=10):
    """Return separate read-only CPU and RSS rankings from macOS ps."""
    try:
        result=subprocess.run(
            ["ps", "-axo", "pid=,pcpu=,rss=,etime=,comm="],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise ValueError("Prozessabfrage ist nicht verfügbar") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Prozessabfrage fehlgeschlagen: {exc}") from exc
    if result.returncode != 0:
        raise ValueError(
            "Prozessabfrage fehlgeschlagen: " + (result.stderr or "unbekannter Fehler")[:500]
        )

    processes=[]
    for line in (result.stdout or "").splitlines():
        parts=line.strip().split(None, 4)
        if len(parts) != 5:
            continue
        try:
            pid=int(parts[0])
            cpu_percent=float(parts[1].replace(",", "."))
            rss_kb=int(parts[2])
        except (TypeError, ValueError):
            continue
        command=parts[4].strip()
        processes.append({
            "pid": pid,
            "name": Path(command).name or command,
            "command": command,
            "cpu_percent": cpu_percent,
            "rss_mb": round(rss_kb / 1024, 1),
            "elapsed": parts[3],
        })

    limit=max(1, min(25, int(limit or 10)))
    return {
        "source": "ps",
        "captured_at": time.time(),
        "metric_note": (
            "CPU und RAM/RSS sind getrennte Messgrößen; es wird kein "
            "künstlicher Gesamtverbrauch berechnet."
        ),
        "cpu_top": sorted(
            processes,
            key=lambda entry: entry["cpu_percent"],
            reverse=True,
        )[:limit],
        "memory_top": sorted(
            processes,
            key=lambda entry: entry["rss_mb"],
            reverse=True,
        )[:limit],
        "process_count": len(processes),
    }


def tool_disk_usage(options=None):
    """Scan approved local roots with the native read-only disk tool."""
    allowed_roots = []
    try:
        workspace = code_workspaces.active_workspace(validate=False)
    except (OSError, ValueError):
        workspace = None
    if isinstance(workspace, dict) and workspace.get("root_path"):
        allowed_roots.append(workspace["root_path"])

    return disk_usage.scan_disk_usage(
        options,
        home=Path.home(),
        allowed_roots=allowed_roots,
    )


READ_ONLY_AGENT_TOOLS = {
    "disk_usage",
    "shell_read",
    "process_usage",
    "system_status",
    "logs_query",
    "batch_status",
    "knowledge_search",
    "code_search",
    "code_files",
    "code_read",
    "code_test",
    "code_diff",
    "web_search",
    "search_web",
    "fetch_url",
}

        # PREPARE tools may create patch metadata, but they must never
        # modify workspace source code directly.
PREPARE_AGENT_TOOLS = {
    "code_patch",
}


def allowed_agent_tools(mode):
    allowed = set(READ_ONLY_AGENT_TOOLS)
    if str(mode or "").strip().lower() == "coding":
        allowed.update(PREPARE_AGENT_TOOLS)
    return allowed



def normalize_json_structural_whitespace(value):
    """
    Normalize Unicode whitespace only outside JSON strings.

    Some local models emit NBSP (U+00A0), for example, when indenting an
    otherwise valid JSON object. Python's JSON parser accepts only JSON
    whitespace defined by RFC 8259 in that position.

    Content inside strings remains unchanged.
    """
    value = str(value or "")

    result = []
    in_string = False
    escaped = False

    for char in value:
        if in_string:
            result.append(char)

            if escaped:
                escaped = False
                continue

            if char == "\\":
                escaped = True
                continue

            if char == '"':
                in_string = False

            continue

        if char == '"':
            in_string = True
            result.append(char)
            continue

    # JSON permits only these whitespace characters structurally:
    # U+0020 SPACE, TAB, LF, and CR.
        #
    # Other Unicode whitespace characters outside strings are
    # safely normalized to regular SPACE characters.
        if char.isspace() and char not in " \t\n\r":
            result.append(" ")
        else:
            result.append(char)

    return "".join(result)


def parse_agent_json(value):
    """Reliably extract exactly one JSON object from a model response."""

    value = str(value or "").strip()

    # Local models occasionally use Unicode whitespace such as
    # NBSP (U+00A0) for JSON indentation. Outside strings, this is
    # not valid JSON whitespace.
    value = normalize_json_structural_whitespace(value)

    if not value:
        raise ValueError(
            "Agent hat kein gültiges JSON geliefert"
        )

    if value.startswith("```"):
        value = re.sub(
            r"^```(?:json)?\s*",
            "",
            value,
            flags=re.I,
        )
        value = re.sub(
            r"\s*```$",
            "",
            value,
        ).strip()

    # Ideal case: the complete response is valid JSON.
    try:
        result = json.loads(value)
        if isinstance(result, dict):
            return result
    except Exception:
        pass

    # Eingebettetes JSON robust finden.
    decoder = json.JSONDecoder()

    for index, char in enumerate(value):
        if char != "{":
            continue

        try:
            result, _end = decoder.raw_decode(value[index:])
        except json.JSONDecodeError:
            continue

        if isinstance(result, dict):
            return result

    raise ValueError(
        "Agent hat kein gültiges JSON geliefert"
    )


def agent_tool_description(include_prepare=False):
    prepare_tools = """

Verfügbare PREPARE-Tools (nur im Coding-Modus):

code_patch
- Erzeugt ausschließlich einen Patch-Vorschlag und verändert keine
  Workspace-Datei.
- Darf ohne Benutzerfreigabe automatisch ausgeführt werden.
- Unterstützt CREATE, MODIFY und DELETE innerhalb des aktiven Workspaces.
- Ein Aufruf ist ein zusammenhängendes Change-Set und darf beliebig viele
  CREATE-, MODIFY- und DELETE-Einträge gemeinsam enthalten.
- CREATE/MODIFY enthalten den vollständigen neuen Dateiinhalt in
  proposed_content. DELETE verwendet operation="DELETE" und keinen neuen
  Inhalt.
- Nach code_patch müssen code_diff und code_test ausgeführt werden.
- Das spätere code_apply benötigt eine ausdrückliche Benutzerfreigabe.
""".rstrip() if include_prepare else ""

    return f"""
Zentrale MLX-Nobby-Fähigkeiten:
{capability_model_text()}

Verfügbare automatisch ausführbare READ-Tools:

disk_usage
- Analysiert große Dateien und Ordner nativ, strukturiert und ausschließlich
  lesend. Verwende dieses Tool immer für lokalen Speicherplatz,
  Speicherverbrauch, volle SSDs und Ranglisten großer Dateien oder Ordner.
- Verwende dafür NICHT shell_read mit du, find, sort, Pipes, Globs oder
  Redirects.
- Ohne Optionen wird sicher der Benutzerordner untersucht.
- Optionale Eingabe im Feld "options":
  {{"path":"/absoluter/freigegebener/Pfad","mode":"files|directories|both",
  "limit":20,"min_size_bytes":104857600,"max_depth":5,
  "include_hidden":true}}
- Bei partial=true fasse die vorhandenen Resultate zusammen und erwähne die
  Warnungen, statt die gesamte Analyse als fehlgeschlagen zu behandeln.

shell_read
- Führt einen einzelnen freigegebenen Diagnosebefehl aus.
- Verwende dafür das JSON-Feld "query".
- Keine Pipes, Redirects oder Shell-Verknüpfungen.
- Erlaubt sind insbesondere:
  ps, pgrep, df, du, uptime, vm_stat, memory_pressure,
  sysctl, lsof, curl sowie docker ps/logs/inspect/stats.
- Beispiel:
  {{"action":"shell_read","reason":"RAM prüfen","query":"vm_stat"}}

process_usage
- Erfasst lokale Prozesse strukturiert und ausschließlich lesend.
- Liefert getrennte Ranglisten für CPU-Prozent und RAM/RSS inklusive
  Prozessname, PID und Laufzeit.
- Verwende dieses Tool bei Fragen nach Apps/Prozessen mit der höchsten
  CPU- oder Speichernutzung. Berechne keinen erfundenen Gesamtverbrauch.

system_status
- System-, RAM- und MLX-Status untersuchen.

logs_query
- Aktuelle Agent-/Server-Logs untersuchen.

batch_status
- Laufende Batch-Jobs und Aufgaben untersuchen.

knowledge_search
- In der lokalen Wissensbasis suchen.

code_search
- Im konfigurierten Code-Workspace suchen.



code_diff
- Zeigt den Unified Diff eines bereits vorbereiteten Patches.
- "query" enthält ausschließlich die patch_id.

code_test
- Testet einen bereits vorbereiteten Patch isoliert.
- Verändert den echten Workspace nicht.
- "query" enthält ausschließlich die patch_id.

code_files

- Findet Dateien im konfigurierten Code-Workspace.
- Verwende "query" für Dateinamen, Funktionsnamen oder Code-Begriffe.
- Das Tool durchsucht Dateipfade und geeignete Textdateien.
- Wenn code_search keine brauchbaren Treffer liefert, verwende code_files.
- Anschließend die relevante Datei mit code_read lesen.

code_read

- Liest eine konkrete Datei aus dem Code-Workspace.
- Im Feld "query" den relativen Dateipfad angeben.
- Wenn die Datei unbekannt ist, zuerst code_search verwenden.

web_search
- Schnelle Webrecherche über SearXNG.
- Sucht und lädt automatisch die relevantesten Seiten.

search_web
- Suche gezielt nach aktuellen Informationen.
- Verwende dafür das JSON-Feld "query".
- Liefert Titel, URL und Snippet, lädt die Seiten aber noch nicht.
- Nutze dieses Tool bevorzugt für mehrstufige Recherche.

fetch_url
- Lade gezielt eine URL aus einem vorherigen search_web-Ergebnis.
- Übergib die vollständige URL im JSON-Feld "query".
- Öffne bevorzugt relevante Primärquellen und seriöse Quellen.
- Du darfst mehrere Quellen nacheinander laden.

Bei Fragen, die aktuelle Webinformationen benötigen:
1. search_web verwenden.
2. Relevante Treffer auswählen.
3. Mit fetch_url mindestens die wichtigsten Quellen öffnen.
4. Bei widersprüchlichen Informationen weitere Quellen prüfen.
5. In der Abschlussantwort die verwendeten Quellen bzw. URLs nennen.
{prepare_tools}
""".strip()


def agent_choose_next_step(goal, observations):
    if not observations and _looks_like_disk_usage_request(goal):
        return {
            "action": "disk_usage",
            "reason": "Große Dateien und Ordner sicher analysieren",
            "options": {},
        }

    system_prompt = f"""
Du bist ein lokaler technischer Diagnose-Agent auf einem Mac.

Deine Aufgabe ist es, ein Nutzerziel selbstständig zu untersuchen.

Du arbeitest iterativ:
PLAN -> TOOL -> OBSERVATION -> PLAN -> TOOL -> ...

Du hast ausschließlich READ-ONLY-Zugriff.

{agent_tool_description()}

Regeln:
- Verändere niemals das System.
- Erfinde keine Tool-Ergebnisse.
- Nutze nur Informationen aus den Observations.
- Wähle immer nur EIN Tool pro Schritt.
- Wiederhole ein Tool nicht grundlos.
- Wenn genug Informationen vorhanden sind, beende die Untersuchung.
- Wenn ein Tool für das Ziel ungeeignet ist, verwende es nicht.
- Maximal {max_steps} Schritte.

Antworte ausschließlich als JSON.

Für einen Tool-Aufruf:

{{
  "action": "tool_name",
  "reason": "Warum dieses Tool jetzt sinnvoll ist",
  "query": "optionale konkrete Suchanweisung"
}}

Wenn die Untersuchung beendet werden kann:

{{
  "action": "final",
  "answer": "Klare abschließende Diagnose bzw. Antwort"
}}
""".strip()

    history = json.dumps(
        observations,
        ensure_ascii=False,
        indent=2,
    )

    answer = observed_agent_llm(
        "agent.legacy.plan",
        [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": (
                    "NUTZERZIEL:\n"
                    + goal
                    + "\n\n"
                    + "BISHERIGE OBSERVATIONS:\n"
                    + history
                ),
            },
        ],
        max_tokens=1000,
        temperature=0.05,
    )

    return parse_agent_json(answer)


def execute_read_only_agent_tool(
    action,
    goal,
    query=None,
    instruction=None,
    files=None,
    options=None,
):
    if (
        action not in READ_ONLY_AGENT_TOOLS
        and action not in PREPARE_AGENT_TOOLS
    ):
        raise ValueError(
            f"Tool nicht für Agent-Ausführung freigegeben: {action}"
        )

    request = ChatActionRequest(
        prompt=query or goal,
        file_context=None,
        instruction=instruction,
    )

    if action == "code_files":
        workspace_id = code_workspaces.active_workspace_id()

        return code_workspaces.list_files(
            workspace_id,
            query,
        )

    if action == "code_read":
        if not query:
            raise ValueError(
                "code_read benötigt einen Dateipfad"
            )

        workspace_id = code_workspaces.active_workspace_id()

        read_query = str(query).strip()

        # -------------------------------------------------
    # Argument guard for code_read
        # -------------------------------------------------
    # code_read may receive only workspace file paths.
    # This prevents a web search query, for example, from being
    # interpreted as a filename by mistake.
        if "\n" in read_query or "\r" in read_query:
            raise ValueError(
                "code_read erwartet einen einzelnen Dateipfad, "
                "keine mehrzeilige Eingabe"
            )

        if re.match(r"(?i)^https?://", read_query):
            raise ValueError(
                "code_read kann keine URL lesen; "
                "verwende dafür fetch_url"
            )

    # Remove the line range before validating the path:
        #   agent/app.py:100-200 -> agent/app.py
        path_candidate = re.sub(
            r":\d+(?:-\d+)?$",
            "",
            read_query,
        ).strip()

        if (
            path_candidate.startswith("/")
            or path_candidate == ".."
            or path_candidate.startswith("../")
            or "/../" in path_candidate
            or path_candidate.endswith("/..")
        ):
            raise ValueError(
                "code_read akzeptiert nur sichere relative "
                "Workspace-Pfade"
            )

    # Typical routing error:
        #   "MLX best practices local inference python"
        #
    # Multiple words without any path or file marker are most
    # likely a search query rather than a filename.
        path_markers = (
            "/",
            "\\",
            ".",
        )

        words = path_candidate.split()

        if (
            len(words) >= 4
            and not any(
                marker in path_candidate
                for marker in path_markers
            )
        ):
            raise ValueError(
                "code_read erhielt wahrscheinlich eine Suchanfrage "
                "statt eines Dateipfads; verwende code_search oder "
                "web_search"
            )

        # If the model puts the requested line range only in
        # "instruction", use it here as a fallback.
        if ":" not in read_query and instruction:
            instruction_text = str(instruction).strip()

            range_match = re.search(
                r"(?i)(?:ab\s+)?zeile\s+(\d+)"
                r"(?:\s*(?:-|bis|bis\s+zeile)\s*(\d+))?",
                instruction_text,
            )

            if range_match:
                fallback_start = int(range_match.group(1))
                fallback_end = (
                    int(range_match.group(2))
                    if range_match.group(2)
                    else fallback_start + 240
                )

                if fallback_end < fallback_start:
                    fallback_end = fallback_start + 240

                read_query = (
                    f"{read_query}:"
                    f"{fallback_start}-{fallback_end}"
                )

    # Supported forms:
        #   agent/app.py
        #   agent/app.py:2880
        #   agent/app.py:2850-3150
        match = re.fullmatch(
            r"(.+?):(\d+)(?:-(\d+))?",
            read_query,
        )

        if match:
            file_path = match.group(1).strip()
            start_line = int(match.group(2))
            end_line = (
                int(match.group(3))
                if match.group(3)
                else start_line + 240
            )

            return code_workspaces.read(
                workspace_id,
                file_path,
                start_line=start_line,
                end_line=end_line,
            )

        return code_workspaces.read(
            workspace_id,
            read_query,
        )

    if action == "code_patch":
        workspace_id = code_workspaces.active_workspace_id()

        if not isinstance(files, list) or not files:
            raise ValueError(
                "code_patch benötigt mindestens eine Datei"
            )

        clean_files = []

        for item in files:
            if not isinstance(item, dict):
                raise ValueError(
                    "Ungültiger code_patch Datei-Eintrag"
                )

            path = str(item.get("path", "")).strip()
            operation = str(item.get("operation") or "").strip().upper()
            proposed_content = item.get("proposed_content")

            if not path:
                raise ValueError(
                    "code_patch Datei ohne Pfad"
                )

            if operation == "DELETE":
                if proposed_content not in {None, ""}:
                    raise ValueError(
                        f"DELETE darf keinen neuen Inhalt für {path} enthalten"
                    )
            elif not isinstance(proposed_content, str):
                raise ValueError(
                    f"code_patch benötigt vollständigen Inhalt für {path}"
                )

            clean_file = {
                "path": path,
                "proposed_content": proposed_content,
            }
            if operation:
                clean_file["operation"] = operation
            clean_files.append(clean_file)

        return code_workspaces.create_patch(
            workspace_id,
            str(instruction or goal),
            clean_files,
        )

    if action == "code_diff":
        if not query:
            raise ValueError(
                "code_diff benötigt eine patch_id"
            )

        patch_id = str(query).strip()

        if not re.fullmatch(r"[a-fA-F0-9]{16}", patch_id):
            raise ValueError(
                "Ungültige patch_id für code_diff"
            )

        return code_workspaces.diff(patch_id)

    if action == "code_test":
        if not query:
            raise ValueError(
                "code_test benötigt eine patch_id"
            )

        patch_id = str(query).strip()

        if not re.fullmatch(r"[a-fA-F0-9]{16}", patch_id):
            raise ValueError(
                "Ungültige patch_id für code_test"
            )

        return code_workspaces.test(patch_id)

    if action == "process_usage":
        return tool_process_usage()

    if action == "disk_usage":
        if options is not None and not isinstance(options, dict):
            raise ValueError("disk_usage options must be an object")
        return tool_disk_usage(options)

    if action == "shell_read":
        if not query:
            raise ValueError(
                "shell_read benötigt einen Diagnosebefehl im Feld query"
            )

        return tool_shell_read(query)

    if action == "system_status":
        return {
            "status": status(),
            "system": system(),
        }

    if action == "logs_query":
        return logs_all(80)

    if action == "batch_status":
        return get_batch_jobs()

    if action == "knowledge_search":
        return tool_knowledge_search(request)

    if action == "code_search":
        return tool_code_search(request)

    if action == "web_search":
        return tool_web_search(request)

    if action == "search_web":
        return tool_search_web(request)

    if action == "fetch_url":
        return tool_fetch_url(request)

    raise ValueError(
        f"Unbekanntes Agent-Tool: {action}"
    )


def run_read_only_agent(goal):
    goal = str(goal or "").strip()

    if not goal:
        raise HTTPException(
            status_code=400,
            detail="Kein Agent-Ziel angegeben",
        )

    observations = []

    for step in range(1, MAX_TOOL_STEPS + 1):
        decision = agent_choose_next_step(
            goal,
            observations,
        )

        action = str(
            decision.get("action", "")
        ).strip()

        if action == "final":
            return {
                "status": "completed",
                "goal": goal,
                "steps": observations,
                "answer": str(
                    decision.get("answer", "")
                ).strip(),
            }

        if action not in READ_ONLY_AGENT_TOOLS:
            observations.append({
                "step": step,
                "action": action,
                "status": "rejected",
                "reason": (
                    "Tool ist nicht für den "
                    "Read-only-Agent freigegeben"
                ),
            })
            continue

        reason = str(
            decision.get("reason", "")
        ).strip()

        query = str(
            decision.get("query", "")
        ).strip()

        tool_options = decision.get("options")
        if not isinstance(tool_options, dict):
            tool_options = {}

        try:
            result = execute_read_only_agent_tool(
                action,
                goal,
                query=query or None,
                options=tool_options,
            )

            observations.append({
                "step": step,
                "action": action,
                "reason": reason,
                "query": query or None,
                "options": tool_options or None,
                "status": "completed",
                "result": result,
            })

        except Exception as exc:
            observations.append({
                "step": step,
                "action": action,
                "reason": reason,
                "query": query or None,
                "options": tool_options or None,
                "status": "failed",
                "error": str(exc),
            })

    final_prompt = """
Die maximale Zahl an Diagnose-Schritten ist erreicht.

Formuliere jetzt ausschließlich eine kurze, klare Abschlussantwort
auf Grundlage der vorhandenen Observations.

Keine neuen Fakten erfinden.
""".strip()

    answer = observed_agent_llm(
        "agent.legacy.final",
        [
            {
                "role": "system",
                "content": final_prompt,
            },
            {
                "role": "user",
                "content": (
                    "ZIEL:\n"
                    + goal
                    + "\n\nOBSERVATIONS:\n"
                    + json.dumps(
                        compact_agent_observations(observations),
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
            },
        ],
        max_tokens=1000,
        temperature=0.05,
    )

    return {
        "status": "max_steps",
        "goal": goal,
        "steps": observations,
        "answer": answer,
    }


class AgentRunRequest(BaseModel):
    goal: str
    mode: str = "diagnostic"
    conversation_context: list[dict] | None = None
    run_id: str | None = None
    trace_id: str | None = None


@app.post("/api/agent/run")
@observability.observed_turn
def api_agent_run(request: AgentRunRequest):
    run_id = validate_agent_run_id(request.run_id) if request.run_id else None

    def progress(status, steps, current_step=None, pending_action=None):
        if run_id:
            update_agent_run_progress(
                run_id,
                request.goal,
                status,
                steps,
                current_step=current_step,
                pending_action=pending_action,
            )

    progress(
        "running",
        [],
        current_step={
            "action": "agent_plan",
            "reason": "Nächsten sicheren Projektschritt planen",
            "status": "running",
        },
    )
    try:
        result = run_agent_v2(
            request.goal,
            mode=request.mode,
            conversation_context=request.conversation_context,
            progress_callback=progress,
        )
        progress(
            result.get("status", "completed"),
            result.get("steps", []),
            pending_action=result.get("pending_action"),
        )
        return result
    except ValueError as exc:
        invalid_model_json=(
            isinstance(exc, json.JSONDecodeError)
            or "kein gültiges JSON" in str(exc)
            or "kein JSON-Objekt" in str(exc)
        )
        if not invalid_model_json:
            progress("failed", [], current_step={
                "action": "agent_error",
                "reason": str(exc),
                "status": "failed",
            })
            raise
        result={
            "status": "failed",
            "goal": request.goal,
            "steps": [],
            "answer": (
                "Der Agent konnte die Modellantwort nicht sicher als Aktion "
                "interpretieren. Es wurde nichts ausgeführt. Bitte versuche "
                "die Anfrage erneut."
            ),
            "error": {
                "code": "invalid_agent_response",
                "detail": str(exc),
            },
        }
        progress(
            "failed",
            [],
            current_step={
                "action": "agent_error",
                "reason": "Ungültiges Antwortformat des Agent-Modells",
                "status": "failed",
            },
        )
        return result
    except Exception as exc:
        progress("failed", [], current_step={
            "action": "agent_error",
            "reason": str(exc),
            "status": "failed",
        })
        raise


@app.get("/api/agent/runs/{run_id}")
def api_agent_run_progress(run_id: str):
    run_id = validate_agent_run_id(run_id)
    with ACTIVE_AGENT_RUNS_LOCK:
        progress = ACTIVE_AGENT_RUNS.get(run_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Agent-Lauf nicht gefunden")
    return progress


def local_file_llm(prompt, max_tokens=800):
    config = load_config(); model = config.get("MODEL"); port = int(config.get("PORT", 8000))
    if not model: raise RuntimeError("Kein aktives MLX-Modell gefunden")
    payload = {"model": model, "messages": [{"role": "system", "content": "Answer precisely in the language of the user's instruction. Do not invent facts; use only the supplied file facts."}, {"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": max_tokens, "chat_template_kwargs": {"enable_thinking": False}}
    request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    call_metrics = observability.ModelCallMetrics(
        purpose=observability.current_call_purpose("file_analysis.call"),
        model=model,
        role="file_analysis",
        backend="mlx_lm",
        messages=payload["messages"],
        context_sources=observability.current_context_sources(
            observability.message_context_counts(
                payload["messages"],
                "document_web",
            )
        ),
    )
    try:
        connect_started = time.monotonic()
        with urllib.request.urlopen(request, timeout=900) as response:
            call_metrics.set_upstream_connect(
                (time.monotonic() - connect_started) * 1000
            )
            result = json.loads(response.read().decode("utf-8"))
        choice = result["choices"][0]
        output = choice["message"]["content"] or ""
        call_metrics.finish(
            usage=result.get("usage"),
            output_text=output,
            finish_reason=choice.get("finish_reason"),
        )
        return output
    except Exception as exc:
        call_metrics.fail(type(exc).__name__)
        raise


def observed_local_file_llm(purpose, prompt, max_tokens=800):
    """Call the file-analysis model with a stable metrics purpose."""
    with observability.model_call_context(purpose):
        return local_file_llm(prompt, max_tokens)


def read_file_excerpt(input_path, selection):
    """Read only an explicitly selected line range from a text file."""
    path = Path(input_path)

    text = path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )
    lines = text.splitlines()

    if not selection:
        return None

    kind = selection.get("kind")

    if kind == "line_range":
        start_line = max(
            1,
            int(selection["start_line"]),
        )
        requested_end_line = max(
            start_line,
            int(selection["end_line"]),
        )

    elif kind == "last_lines":
        count = max(
            1,
            min(
                int(selection["count"]),
                FILE_EXCERPT_MAX_LINES,
            ),
        )

        requested_end_line = len(lines)
        start_line = max(
            1,
            requested_end_line - count + 1,
        )

    else:
        return None

    # Never read more than the configured safety limit.
    end_line = min(
        requested_end_line,
        start_line + FILE_EXCERPT_MAX_LINES - 1,
        len(lines),
    )

    selected_lines = lines[
        start_line - 1:end_line
    ]

    rendered_lines = []
    total_chars = 0
    truncated_lines = []

    for line_number, line in enumerate(
        selected_lines,
        start=start_line,
    ):
        rendered = line

        if len(rendered) > FILE_EXCERPT_MAX_CHARS_PER_LINE:
            rendered = (
                rendered[:FILE_EXCERPT_MAX_CHARS_PER_LINE]
                + " … [LINE TRUNCATED]"
            )
            truncated_lines.append(line_number)

        entry = f"{line_number}: {rendered}"

        remaining = FILE_EXCERPT_MAX_CHARS - total_chars

        if remaining <= 0:
            break

        if len(entry) > remaining:
            entry = entry[:remaining] + " … [EXCERPT TRUNCATED]"
            rendered_lines.append(entry)
            total_chars += len(entry)
            break

        rendered_lines.append(entry)
        total_chars += len(entry) + 1

    numbered = "\n".join(rendered_lines)

    actual_end_line = (
        start_line + len(selected_lines) - 1
        if selected_lines
        else start_line - 1
    )

    return {
        "kind": "line_range",
        "start_line": start_line,
        "end_line": actual_end_line,
        "requested_end_line": requested_end_line,
        "file_line_count": len(lines),
        "line_count": len(rendered_lines),
        "requested_line_count": len(selected_lines),
        "truncated": (
            len(rendered_lines) < len(selected_lines)
            or bool(truncated_lines)
        ),
        "truncated_lines": truncated_lines,
        "content_chars": len(numbered),
        "content": numbered,
    }


FILE_ANALYSIS_REDUCE_GROUP_SIZE = 12


def file_analysis_reduction_limits(item_count):
    """Return the exact depth and call count for file-analysis reduction."""
    width = max(0, int(item_count or 0))

    if width <= FILE_ANALYSIS_REDUCE_GROUP_SIZE:
        return 0, 0

    depth = 0
    calls = 0

    while width > 1:
        next_width = (
            width + FILE_ANALYSIS_REDUCE_GROUP_SIZE - 1
        ) // FILE_ANALYSIS_REDUCE_GROUP_SIZE

        if next_width >= width:
            raise RuntimeError(
                "File analysis reduction cannot make progress"
            )

        depth += 1
        calls += next_width
        width = next_width

    return depth, calls


def reduce_file_analysis_maps(map_results):
    """Reduce ordered map results through a finite, bounded tree."""
    current_level = list(map_results or [])

    if len(current_level) <= FILE_ANALYSIS_REDUCE_GROUP_SIZE:
        return "\n\n".join(current_level)

    max_depth, max_calls = file_analysis_reduction_limits(
        len(current_level)
    )
    depth = 0
    calls = 0

    while len(current_level) > 1:
        if depth >= max_depth:
            raise RuntimeError(
                "File analysis reduction exceeded its derived depth limit"
            )

        groups = [
            current_level[index:index + FILE_ANALYSIS_REDUCE_GROUP_SIZE]
            for index in range(
                0,
                len(current_level),
                FILE_ANALYSIS_REDUCE_GROUP_SIZE,
            )
        ]
        next_level = []

        for group in groups:
            if calls >= max_calls:
                raise RuntimeError(
                    "File analysis reduction exceeded its derived call limit"
                )

            next_level.append(
                observed_local_file_llm(
                    "file_analysis.reduce",
                    "Condense these partial results without inventing facts:\n"
                    + "\n\n".join(group),
                    900,
                )
            )
            calls += 1

        if len(next_level) >= len(current_level):
            raise RuntimeError(
                "File analysis reduction did not decrease its level size"
            )

        current_level = next_level
        depth += 1

    if calls != max_calls:
        raise RuntimeError(
            "File analysis reduction did not use its derived call count"
        )

    return current_level[0]


def run_file_analysis_job(job_id):
    trace_token = None
    trace_id = None
    try:
        with BATCH_LOCK:
            jobs = load_batch_jobs(); job = jobs.get(job_id)
            if not job: return
            job.update({"status": "running", "started_at": time.time(), "error": None}); jobs[job_id] = job; save_batch_jobs(jobs)
        trace_id = observability.ensure_trace_id(job.get("trace_id"))
        trace_token = observability.bind_trace_id(trace_id)
        operation = job["operation"]
        selection = job.get("selection")

        if selection:
            excerpt = read_file_excerpt(
                job["input_path"],
                selection,
            )

            if excerpt is not None:
                answer = observed_local_file_llm(
                    "file_analysis.excerpt",
                    "You are answering a question about an exact excerpt "
                    "from a file.\n"
                    "Use ONLY the lines supplied below.\n"
                    "Do not refer to a sample, preview, probe, metadata view, "
                    "or the rest of the file.\n"
                    "Do not claim that line breaks are unavailable.\n"
                    "The line numbers shown below are the actual original "
                    "file line numbers.\n"
                    "If the user asks for a summary, summarize only these "
                    "lines.\n\n"
                    "EXACT FILE EXCERPT:\n"
                    + excerpt["content"]
                    + "\n\nUser request:\n"
                    + job["instruction"],
                    1200,
                )

                with BATCH_LOCK:
                    jobs = load_batch_jobs()
                    jobs[job_id].update({
                        "status": "completed",
                        "selection": selection,
                        "excerpt": {
                            key: value
                            for key, value in excerpt.items()
                            if key != "content"
                        },
                        "result": answer,
                        "processed_chunks": 1,
                        "total_chunks": 1,
                        "mlx_calls": 1,
                        "finished_at": time.time(),
                    })
                    save_batch_jobs(jobs)

                return

        metadata = analyze_file_structure(job["input_path"])

        if operation == "inspect":
            facts = dict(metadata)
            sample = facts.pop("sample", "")
            sample_structure = facts.pop("sample_structure", None)

            inspect_context = (
                "Deterministically extracted facts about the COMPLETE file:\n"
                + json.dumps(facts, ensure_ascii=False, indent=2)
            )

            if sample_structure is not None:
                inspect_context += (
                    "\n\nRepresentative parsed structure:\n"
                    + json.dumps(
                        sample_structure,
                        ensure_ascii=False,
                        indent=2,
                    )
                )

            if sample:
                inspect_context += (
                    "\n\nBeginning of file (SAMPLE ONLY; "
                    "do not treat this sample as the complete file):\n"
                    + sample
                )

            answer = observed_local_file_llm(
                "file_analysis.inspect",
                inspect_context
                + "\n\nImportant rules:\n"
                + "- The metadata above describes the complete file.\n"
                + "- Never claim the file is empty when byte_size, "
                  "record_count, line_count, or estimated_tokens show content.\n"
                + "- For JSON, report the top-level type, record count, "
                  "important keys, and apparent purpose when available.\n"
                + "- Distinguish deterministic facts from interpretation.\n"
                + "- Answer directly in the language of the user's request.\n"
                + "\nUser request:\n"
                + job["instruction"],
                1200,
            )
            with BATCH_LOCK:
                jobs = load_batch_jobs(); jobs[job_id].update({"status": "completed", "metadata": metadata, "result": answer, "processed_chunks": 1, "total_chunks": 1, "mlx_calls": 1, "finished_at": time.time()}); save_batch_jobs(jobs)
            return
        text = Path(job["input_path"]).read_text(encoding="utf-8", errors="replace")
        chunks = split_batch_content(text, metadata.get("detected_type", "text"), job["chunk_tokens"])
        with BATCH_LOCK:
            jobs = load_batch_jobs(); jobs[job_id].update({"metadata": metadata, "total_chunks": len(chunks)}); save_batch_jobs(jobs)
        maps = []
        for index, chunk in enumerate(chunks, 1):
            while True:
                with BATCH_LOCK: status = load_batch_jobs().get(job_id, {}).get("status")
                if status == "cancelled": return
                if status != "paused": break
                time.sleep(1)
            task = "Summarize this file excerpt concisely." if operation == "summarize" else "Analyze this file excerpt concisely: patterns, anomalies, problems, and important facts."
            maps.append(observed_local_file_llm(
                "file_analysis.map",
                task + "\n\nEXCERPT:\n" + chunk,
                500,
            ))
            checkpoint = batch_checkpoint_path(job_id, index); temporary = checkpoint.with_suffix(".tmp"); temporary.write_text(maps[-1], encoding="utf-8"); temporary.replace(checkpoint)
            with BATCH_LOCK:
                jobs = load_batch_jobs(); current = jobs[job_id]; current["processed_chunks"] = index; current["mlx_calls"] = int(current.get("mlx_calls", 0)) + 1; current["eta_seconds"] = None; save_batch_jobs(jobs)
        reduced_results = reduce_file_analysis_maps(maps)
        answer = observed_local_file_llm("file_analysis.final", "File metadata:\n" + json.dumps({key: value for key, value in metadata.items() if key not in ("sample", "sample_structure")}, ensure_ascii=False) + "\n\nResults:\n" + (reduced_results if maps else "No readable content found.") + "\n\nAnswer the user's request: " + job["instruction"], 1200)
        with BATCH_LOCK:
            jobs = load_batch_jobs(); jobs[job_id].update({"status": "completed", "result": answer, "finished_at": time.time()}); save_batch_jobs(jobs)
    except Exception as exc:
        with BATCH_LOCK:
            jobs = load_batch_jobs()
            if job_id in jobs: jobs[job_id].update({"status": "failed", "error": str(exc), "finished_at": time.time()}); save_batch_jobs(jobs)
    finally:
        if trace_id:
            with BATCH_LOCK:
                jobs = load_batch_jobs()
                if job_id in jobs:
                    jobs[job_id]["model_metrics"] = (
                        observability.trace_snapshot(trace_id)
                    )
                    save_batch_jobs(jobs)
        if trace_token is not None:
            observability.reset_trace_id(trace_token)
        unregister_batch_worker(job_id)


@locked_batch_start
def start_file_analysis_job(job_id):
    thread = threading.Thread(target=run_file_analysis_job, args=(job_id,), daemon=True, name=f"file-analysis-{job_id}")
    register_batch_worker(job_id, thread)
    thread.start()


def call_mlx_transform(
    *,
    text,
    instruction,
    model,
    port,
    system_prompt,
    timeout=900,
):
    """Run one deterministic MLX text transformation and return plain text."""
    input_text = str(text or "")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": (
                    "TRANSFORMATIONS-ANWEISUNG:\n"
                    + str(instruction or "")
                    + "\n\n"
                    + "DATEI-ABSCHNITT:\n"
                    + input_text
                ),
            },
        ],
        "temperature": 0.0,
        "max_tokens": batch_max_output_tokens(
            max(
                1,
                estimate_batch_tokens(input_text),
            )
        ),
        "chat_template_kwargs": {
            "enable_thinking": False,
        },
    }

    request = urllib.request.Request(
        f"http://127.0.0.1:{int(port)}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )
    call_metrics = observability.ModelCallMetrics(
        purpose=observability.current_call_purpose("batch.transform"),
        model=model,
        role="batch",
        backend="mlx_lm",
        messages=payload["messages"],
        context_sources=observability.current_context_sources(
            observability.message_context_counts(
                payload["messages"],
                "document_web",
            )
        ),
    )
    try:
        connect_started = time.monotonic()
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            call_metrics.set_upstream_connect(
                (time.monotonic() - connect_started) * 1000
            )
            result = json.loads(
                response.read().decode("utf-8")
            )
    except Exception as exc:
        call_metrics.fail(type(exc).__name__)
        raise

    try:
        choice = result["choices"][0]
        output = choice["message"]["content"] or ""
        call_metrics.finish(
            usage=result.get("usage"),
            output_text=output,
            finish_reason=choice.get("finish_reason"),
        )
        return output
    except Exception as exc:
        call_metrics.fail(type(exc).__name__)
        raise RuntimeError(
            f"Ungültige MLX-Antwort: {exc}"
        ) from exc





def call_mlx_json_freetext_batch(
    *,
    targets,
    instruction,
    model,
    port,
):
    """Transform only selected JSON free-text values via MLX."""
    request_items = []

    for index, target in enumerate(targets):
        request_items.append({
            "id": index,
            "text": str(target.get("text") or ""),
        })

    batch_text = json.dumps(
        request_items,
        ensure_ascii=False,
        indent=2,
    )

    system_prompt = """
Du bearbeitest ausschließlich die Textwerte eines JSON-Arrays.

Jeder Eintrag besitzt:
- id
- text

Regeln:
- Die id darf niemals verändert werden.
- Verändere ausschließlich text entsprechend der Anweisung.
- Anzahl und Reihenfolge der Einträge müssen exakt erhalten bleiben.
- Entferne keine Einträge.
- Füge keine Einträge hinzu.
- Gib ausschließlich ein valides JSON-Array zurück.
- Keine Erklärungen.
- Keine Markdown-Codeblöcke.
""".strip()

    transformed = call_mlx_transform(
        text=batch_text,
        instruction=instruction,
        model=model,
        port=port,
        system_prompt=system_prompt,
    )

    try:
        parsed = json.loads(transformed)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "MLX-Freitext-Batch ist kein valides JSON: "
            + str(exc)
        ) from exc

    if not isinstance(parsed, list):
        raise RuntimeError(
            "MLX-Freitext-Batch muss ein JSON-Array zurückgeben"
        )

    if len(parsed) != len(request_items):
        raise RuntimeError(
            "MLX-Freitext-Batch hat eine unerwartete Anzahl Einträge"
        )

    result = []

    for expected, returned in zip(request_items, parsed):
        if not isinstance(returned, dict):
            raise RuntimeError(
                "MLX-Freitext-Batch enthält einen ungültigen Eintrag"
            )

        if returned.get("id") != expected["id"]:
            raise RuntimeError(
                "MLX-Freitext-Batch hat eine ID verändert"
            )

        returned_text = returned.get("text")

        if not isinstance(returned_text, str):
            raise RuntimeError(
                "MLX-Freitext-Batch enthält keinen gültigen Textwert"
            )

        result.append(returned_text)

    return result


def batch_worker_is_alive(job_id):
    with BATCH_WORKERS_LOCK:
        thread = BATCH_WORKERS.get(job_id)

        if not thread:
            return False

        if not thread.is_alive():
            BATCH_WORKERS.pop(
                job_id,
                None,
            )
            return False

        return True


def register_batch_worker(job_id, thread):
    with BATCH_WORKERS_LOCK:
        BATCH_WORKERS[job_id] = thread


def unregister_batch_worker(job_id):
    with BATCH_WORKERS_LOCK:
        BATCH_WORKERS.pop(
            job_id,
            None,
        )



def batch_checkpoint_directory(job_id):
    return batch_state.checkpoint_directory(
        Path.home()
        / ".config/mlx-web/batch/checkpoints",
        job_id,
    )


def batch_checkpoint_path(job_id, chunk_index):
    return batch_state.checkpoint_path(
        batch_checkpoint_directory(job_id),
        chunk_index,
    )


def completed_batch_checkpoints(job_id):
    return batch_state.completed_checkpoints(
        batch_checkpoint_directory(job_id)
    )


def run_batch_transform_job(job_id):
    with BATCH_LOCK:
        jobs = load_batch_jobs()
        job = jobs.get(job_id)

        if not job:
            return

        job["status"] = "running"
        job["started_at"] = time.time()
        job["error"] = None

        jobs[job_id] = job
        save_batch_jobs(jobs)

    trace_id = observability.ensure_trace_id(job.get("trace_id"))
    trace_token = observability.bind_trace_id(trace_id)

    try:
        input_path = Path(job["input_path"])
        output_path = Path(job["output_path"])

        analysis = analyze_input_file(
            input_path
        )

        encoding = analysis.get("encoding", "utf-8")
        try:
            text = decode_batch_bytes(
                input_path.read_bytes(),
                encoding,
                errors=(
                    "replace"
                    if encoding == "utf-8-replace"
                    else "strict"
                ),
            )
        except (UnicodeDecodeError, LookupError):
            text = decode_batch_bytes(
                input_path.read_bytes(),
                "utf-8",
                errors="replace",
            )

        # Automatische JSON-Reparatur
        if (
            analysis.get("detected_type") == "json"
            and analysis.get("repairable")
            and analysis.get("repair")
                == "sanitize_invalid_json_escapes"
        ):
            text = sanitize_invalid_json_escapes(
                text
            )

        detected_type = analysis.get(
            "detected_type",
            job.get("file_type", "text")
        )
        instruction_plan = classify_batch_instruction(
            job["instruction"]
        )
        batch_mode = instruction_plan.get("mode", "llm")
        fast_operations = instruction_plan.get("fast_operations", [])
        llm_operations = instruction_plan.get("llm_operations", [])

        if (
            detected_type == "json"
            and not analysis.get("valid")
            and not analysis.get("repairable")
        ):
            with BATCH_LOCK:
                jobs = load_batch_jobs()
                if job_id in jobs:
                    jobs[job_id].update({
                        "analysis": analysis,
                        "effective_file_type": "json",
                        "effective_chunk_tokens": 0,
                        "estimated_input_tokens": analysis.get(
                            "estimated_input_tokens",
                            estimate_batch_tokens(text),
                        ),
                        "total_chunks": 0,
                        "repair_strategy": "none",
                        "processing_mode": batch_mode,
                        "instruction_plan": instruction_plan,
                    })
                    save_batch_jobs(jobs)
            raise RuntimeError(invalid_json_error(analysis))


            # Fast JSON PII path:
            # anonymize structured fields and clearly identifiable free text
            # deterministically. Send only genuine remaining cases to the LLM.
        if (
            detected_type == "json"
            and batch_mode in {"fast", "hybrid"}
            and instruction_plan.get("operations")
        ):
            try:
                json_value = json.loads(text)
            except json.JSONDecodeError:
                json_value = None

            if json_value is not None:
                json_value, structured_changes = (
                    transform_structured_json_pii(
                        json_value,
                        instruction_plan["operations"],
                    )
                )

                freetext_targets = collect_json_freetext_targets(
                    json_value
                )

                llm_targets = []
                deterministic_freetext_changes = 0

                for target in freetext_targets:
                    original_value = target["text"]

                    cleaned_value = apply_deterministic_transform(
                        original_value,
                        fast_operations,
                    )

                    cleaned_value = apply_deterministic_freetext_pii(
                        cleaned_value,
                        llm_operations,
                    )

                    if cleaned_value != original_value:
                        deterministic_freetext_changes += 1

                    set_json_path_value(
                        json_value,
                        target["path"],
                        cleaned_value,
                    )

                    if (
                        batch_mode == "hybrid"
                        and hybrid_chunk_needs_llm(
                            cleaned_value,
                            llm_operations,
                        )
                    ):
                        llm_targets.append({
                            "path": target["path"],
                            "text": cleaned_value,
                        })

            # Do not send the complete JSON file to the model for remaining
            # semantic cases. Process only the relevant free-text values in
            # small, structured batches.
                freetext_batches = build_json_freetext_batches(
                    llm_targets
                )

                freetext_plan_payload = json.dumps(
                    {
                        "instruction": job["instruction"],
                        "targets": [
                            {
                                "path": list(target["path"]),
                                "text": target["text"],
                            }
                            for target in llm_targets
                        ],
                        "max_items": JSON_FREETEXT_BATCH_MAX_ITEMS,
                        "max_tokens": JSON_FREETEXT_BATCH_MAX_TOKENS,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )

                freetext_plan_id = hashlib.sha256(
                    freetext_plan_payload.encode("utf-8")
                ).hexdigest()[:16]

                total_freetext_batches = len(
                    freetext_batches
                )

                processed_freetext_batches = 0

                config = None
                model = None
                port = None

                if freetext_batches:
                    config = load_config()
                    model = config.get("MODEL")
                    port = int(
                        config.get("PORT", 8000)
                    )

                    if not model:
                        raise RuntimeError(
                            "Kein aktives MLX-Modell gefunden"
                        )

                with BATCH_LOCK:
                    jobs = load_batch_jobs()

                    if job_id in jobs:
                        jobs[job_id].update({
                            "analysis": analysis,
                            "effective_file_type": "json",
                            "effective_chunk_tokens": (
                                JSON_FREETEXT_BATCH_MAX_TOKENS
                                if freetext_batches
                                else 0
                            ),
                            "estimated_input_tokens": analysis.get(
                                "estimated_input_tokens",
                                estimate_batch_tokens(text),
                            ),
                            "total_chunks": total_freetext_batches,
                            "processed_chunks": 0,
                            "processing_mode": batch_mode,
                            "instruction_plan": instruction_plan,
                            "structured_pii_changes": (
                                structured_changes
                            ),
                            "deterministic_freetext_changes": (
                                deterministic_freetext_changes
                            ),
                            "freetext_targets": len(
                                freetext_targets
                            ),
                            "llm_freetext_targets": len(
                                llm_targets
                            ),
                            "freetext_batch_plan_id": (
                                freetext_plan_id
                            ),
                        })

                        save_batch_jobs(jobs)

                for batch_index, batch in enumerate(
                    freetext_batches,
                    start=1,
                ):
                    checkpoint_path = (
                        batch_checkpoint_directory(job_id)
                        / (
                            "freetext-"
                            + freetext_plan_id
                            + "-"
                            + f"{batch_index:08d}"
                            + ".json"
                        )
                    )

                        # Reuse successfully processed batches directly when
                        # resuming the job.
                    if checkpoint_path.exists():
                        try:
                            checkpoint_values = json.loads(
                                checkpoint_path.read_text(
                                    encoding="utf-8"
                                )
                            )

                            if (
                                not isinstance(
                                    checkpoint_values,
                                    list,
                                )
                                or len(checkpoint_values)
                                != len(batch)
                                or not all(
                                    isinstance(item, str)
                                    for item in checkpoint_values
                                )
                            ):
                                raise ValueError(
                                    "Ungültiger Freitext-Checkpoint"
                                )

                            for target, replacement_value in zip(
                                batch,
                                checkpoint_values,
                            ):
                                set_json_path_value(
                                    json_value,
                                    target["path"],
                                    replacement_value,
                                )

                            processed_freetext_batches += 1

                            with BATCH_LOCK:
                                jobs = load_batch_jobs()

                                if job_id in jobs:
                                    jobs[job_id][
                                        "processed_chunks"
                                    ] = (
                                        processed_freetext_batches
                                    )

                                    jobs[job_id][
                                        "checkpoint_count"
                                    ] = (
                                        processed_freetext_batches
                                    )

                                    save_batch_jobs(jobs)

                            continue

                        except Exception:
                        # Invalid or outdated checkpoint:
                        # rerun the batch safely.
                            checkpoint_path.unlink(
                                missing_ok=True
                            )

                    # Honor pause and cancellation before each LLM batch.
                    while True:
                        with BATCH_LOCK:
                            jobs = load_batch_jobs()
                            current_job = jobs.get(
                                job_id,
                                {},
                            )
                            current_status = (
                                current_job.get("status")
                            )

                        if current_status == "cancelled":
                            with BATCH_LOCK:
                                jobs = load_batch_jobs()

                                if job_id in jobs:
                                    jobs[job_id][
                                        "finished_at"
                                    ] = time.time()

                                    jobs[job_id][
                                        "current_chunk"
                                    ] = None

                                    save_batch_jobs(jobs)

                            return

                        if current_status == "paused":
                            time.sleep(1)
                            continue

                        break

                    batch_started_at = time.time()

                    with BATCH_LOCK:
                        jobs = load_batch_jobs()

                        if job_id in jobs:
                            jobs[job_id][
                                "current_chunk"
                            ] = batch_index

                            jobs[job_id][
                                "current_chunk_started_at"
                            ] = batch_started_at

                    # This counter records actual requests to MLX.
                            jobs[job_id]["mlx_calls"] = int(
                                jobs[job_id].get(
                                    "mlx_calls",
                                    0,
                                )
                            ) + 1

                            jobs[job_id]["llm_chunks"] = int(
                                jobs[job_id].get(
                                    "llm_chunks",
                                    0,
                                )
                            ) + 1

                            save_batch_jobs(jobs)

                    transformed_values = (
                        call_mlx_json_freetext_batch(
                            targets=batch,
                            instruction=job["instruction"],
                            model=model,
                            port=port,
                        )
                    )

                    for target, replacement_value in zip(
                        batch,
                        transformed_values,
                    ):
                        set_json_path_value(
                            json_value,
                            target["path"],
                            replacement_value,
                        )

                    temporary_checkpoint = (
                        checkpoint_path.with_suffix(
                            checkpoint_path.suffix + ".tmp"
                        )
                    )

                    temporary_checkpoint.write_text(
                        json.dumps(
                            transformed_values,
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )

                    temporary_checkpoint.replace(
                        checkpoint_path
                    )

                    processed_freetext_batches += 1

                    batch_duration = (
                        time.time() - batch_started_at
                    )

                    with BATCH_LOCK:
                        jobs = load_batch_jobs()

                        if job_id in jobs:
                            current_job = jobs[job_id]

                            previous_average = float(
                                current_job.get(
                                    "average_chunk_seconds"
                                ) or 0
                            )

                            if (
                                processed_freetext_batches <= 1
                                or previous_average <= 0
                            ):
                                average = batch_duration
                            else:
                                average = (
                                    (
                                        previous_average
                                        * (
                                            processed_freetext_batches
                                            - 1
                                        )
                                    )
                                    + batch_duration
                                ) / processed_freetext_batches

                            current_job.update({
                                "processed_chunks": (
                                    processed_freetext_batches
                                ),
                                "checkpoint_count": (
                                    processed_freetext_batches
                                ),
                                "last_chunk_seconds": (
                                    batch_duration
                                ),
                                "average_chunk_seconds": (
                                    average
                                ),
                                "current_chunk": None,
                                "current_chunk_started_at": None,
                                "resume_from_chunk": (
                                    processed_freetext_batches + 1
                                    if processed_freetext_batches
                                    < total_freetext_batches
                                    else None
                                ),
                            })

                            save_batch_jobs(jobs)

                # Serialize the original structure exactly once after all
                # deterministic and semantic batches finish.
                output_text = json.dumps(
                    json_value,
                    ensure_ascii=False,
                    indent=2,
                ) + "\n"

                # Harte Abschlussvalidierung.
                json.loads(output_text)

                output_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                temporary_output = output_path.with_suffix(
                    output_path.suffix + ".tmp"
                )

                write_batch_text(
                    temporary_output,
                    output_text,
                    encoding,
                )

                temporary_output.replace(
                    output_path
                )

                with BATCH_LOCK:
                    jobs = load_batch_jobs()

                    if job_id in jobs:
                        jobs[job_id].update({
                            "analysis": analysis,
                            "effective_file_type": "json",
                            "effective_chunk_tokens": (
                                JSON_FREETEXT_BATCH_MAX_TOKENS
                                if freetext_batches
                                else 0
                            ),
                            "estimated_input_tokens": analysis.get(
                                "estimated_input_tokens",
                                estimate_batch_tokens(text),
                            ),
                            "total_chunks": (
                                total_freetext_batches
                            ),
                            "processed_chunks": (
                                processed_freetext_batches
                            ),
                            "processing_mode": batch_mode,
                            "instruction_plan": (
                                instruction_plan
                            ),
                            "structured_pii_changes": (
                                structured_changes
                            ),
                            "deterministic_freetext_changes": (
                                deterministic_freetext_changes
                            ),
                            "freetext_targets": len(
                                freetext_targets
                            ),
                            "llm_freetext_targets": len(
                                llm_targets
                            ),
                            "output_name": output_path.name,
                            "output_size": (
                                output_path.stat().st_size
                            ),
                            "output_mime_type": (
                                "application/json"
                            ),
                            "pii_audit": (
                                deterministic_pii_audit(
                                    output_text
                                )
                            ),
                            "current_chunk": None,
                            "current_chunk_started_at": None,
                            "resume_from_chunk": None,
                            "status": "completed",
                            "finished_at": time.time(),
                            "error": None,
                        })

                        save_batch_jobs(jobs)

                return

        requested_tokens = int(
            job.get(
                "chunk_tokens",
                job.get("chunk_size", BATCH_SINGLE_CHUNK_TOKENS)
            )
        )

        recommended_tokens = int(
            analysis.get(
                "recommended_chunk_tokens",
                requested_tokens
            )
        )

        chunk_tokens = min(
            requested_tokens,
            recommended_tokens
        )

        chunks = split_batch_content(
            text,
            detected_type,
            chunk_tokens,
        )
        checkpoint_plan_id = batch_checkpoint_plan_id(
            text,
            job["instruction"],
            detected_type,
            chunk_tokens,
            analysis,
        )
        previous_checkpoint_plan_id = job.get("checkpoint_plan_id")

        with BATCH_LOCK:
            jobs = load_batch_jobs()

            if job_id in jobs:
                jobs[job_id].update({
                    "analysis": analysis,
                    "effective_file_type": detected_type,
                    "effective_chunk_tokens": chunk_tokens,
                    "estimated_input_tokens": analysis.get(
                        "estimated_input_tokens",
                        estimate_batch_tokens(text),
                    ),
                    "total_chunks": len(chunks),
                    "repair_strategy": (
                        analysis.get("repair") or "none"
                    ),
                    "checkpoint_plan_id": checkpoint_plan_id,
                })

                save_batch_jobs(jobs)

        config = load_config()

        model = config.get("MODEL")
        port = int(config.get("PORT", 8000))

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # ----------------------------------------------------
        # Checkpoint-basierte Resume-Logik
        # ----------------------------------------------------

        completed = (
            set(completed_batch_checkpoints(job_id))
            if previous_checkpoint_plan_id == checkpoint_plan_id
            else set()
        )

        # Count only contiguous completed chunks starting at 1.
        contiguous_completed = 0

        while (
            contiguous_completed + 1
            in completed
        ):
            contiguous_completed += 1

        start_chunk_index = min(
            contiguous_completed,
            len(chunks),
        )

        with BATCH_LOCK:
            jobs = load_batch_jobs()

            if job_id in jobs:
                jobs[job_id]["processed_chunks"] = (
                    start_chunk_index
                )
                jobs[job_id]["current_chunk"] = None
                jobs[job_id]["current_chunk_started_at"] = None
                jobs[job_id]["resume_from_chunk"] = (
                    start_chunk_index + 1
                    if start_chunk_index < len(chunks)
                    else None
                )
                jobs[job_id]["checkpoint_count"] = len(
                    completed
                )

                save_batch_jobs(jobs)

        system_prompt = """
Du bearbeitest Dateiinhalte stapelweise.

Halte dich exakt an die Transformations-Anweisung.
Verändere nichts, was nicht ausdrücklich verlangt wurde.
Erhalte Syntax, Struktur, Reihenfolge und Formatierung so weit wie möglich.
Gib ausschließlich den bearbeiteten Inhalt zurück.
Keine Erklärungen.
Keine Markdown-Codeblöcke.
""".strip()

        with BATCH_LOCK:
            jobs = load_batch_jobs()

            if job_id in jobs:
                jobs[job_id]["processing_mode"] = batch_mode
                jobs[job_id]["instruction_plan"] = instruction_plan

                save_batch_jobs(jobs)

        for index, chunk in enumerate(
            chunks[start_chunk_index:],
            start=start_chunk_index + 1,
        ):
            chunk_started_at = time.time()

            with BATCH_LOCK:
                jobs = load_batch_jobs()

                if job_id in jobs:
                    jobs[job_id]["current_chunk"] = index
                    jobs[job_id]["current_chunk_started_at"] = chunk_started_at

                    save_batch_jobs(jobs)

            # Check for pause or cancellation
            while True:
                with BATCH_LOCK:
                    jobs = load_batch_jobs()
                    current_job = jobs.get(job_id, {})
                    current_status = current_job.get("status")

                if current_status == "cancelled":
                    with BATCH_LOCK:
                        jobs = load_batch_jobs()

                        if job_id in jobs:
                            jobs[job_id]["finished_at"] = time.time()
                            save_batch_jobs(jobs)

                    return

                if current_status == "paused":
                    time.sleep(1)
                    continue

                break

            working_chunk = chunk

            if fast_operations:
                working_chunk = apply_deterministic_transform(
                    working_chunk,
                    fast_operations,
                )

            if batch_mode == "fast":
                transformed = working_chunk
                with BATCH_LOCK:
                    jobs = load_batch_jobs()
                    if job_id in jobs:
                        jobs[job_id]["fast_only_chunks"] = int(jobs[job_id].get("fast_only_chunks", 0)) + 1
                        save_batch_jobs(jobs)

            elif (
                batch_mode == "hybrid"
                and not hybrid_chunk_needs_llm(
                    working_chunk,
                    llm_operations,
                )
            ):
                transformed = working_chunk
                with BATCH_LOCK:
                    jobs = load_batch_jobs()
                    if job_id in jobs:
                        jobs[job_id]["fast_only_chunks"] = int(jobs[job_id].get("fast_only_chunks", 0)) + 1
                        jobs[job_id]["skipped_llm_chunks"] = int(jobs[job_id].get("skipped_llm_chunks", 0)) + 1
                        save_batch_jobs(jobs)

            else:
                if not model:
                    raise RuntimeError(
                        "Kein aktives MLX-Modell gefunden"
                    )
                with BATCH_LOCK:
                    jobs = load_batch_jobs()
                    if job_id in jobs:
                        jobs[job_id]["llm_chunks"] = int(jobs[job_id].get("llm_chunks", 0)) + 1
                        save_batch_jobs(jobs)
                estimated_input_tokens = max(
                    1,
                    estimate_batch_tokens(working_chunk),
                )

                max_output_tokens = batch_max_output_tokens(
                    estimated_input_tokens
                )

                payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content":
                                "TRANSFORMATIONS-ANWEISUNG:\n"
                                + job["instruction"]
                                + "\n\n"
                                + "DATEI-ABSCHNITT:\n"
                                + working_chunk,
                        },
                    ],
                    "temperature": 0.0,
                    "max_tokens": max_output_tokens,
                    "chat_template_kwargs": {
                        "enable_thinking": False
                    },
                }

                pending_parts = [
                    {
                        "text": working_chunk,
                        "tokens": chunk_tokens,
                    }
                ]

                transformed_parts = []

                while pending_parts:
                    part = pending_parts.pop(0)

                    part_text = part["text"]
                    part_tokens = int(part["tokens"])

                    part_input_tokens = max(
                        1,
                        estimate_batch_tokens(part_text),
                    )

                    payload["max_tokens"] = batch_max_output_tokens(
                        part_input_tokens
                    )

                    payload["messages"][1]["content"] = (
                        "TRANSFORMATIONS-ANWEISUNG:\n"
                        + job["instruction"]
                        + "\n\n"
                        + "DATEI-ABSCHNITT:\n"
                        + part_text
                    )

                    request = urllib.request.Request(
                        f"http://127.0.0.1:{port}/v1/chat/completions",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={
                            "Content-Type": "application/json"
                        },
                        method="POST",
                    )

                    with BATCH_LOCK:
                        jobs = load_batch_jobs()
                        if job_id in jobs:
                            jobs[job_id]["mlx_calls"] = int(
                                jobs[job_id].get("mlx_calls", 0)
                            ) + 1
                            save_batch_jobs(jobs)

                    call_metrics = observability.ModelCallMetrics(
                        purpose="batch.transform",
                        model=model,
                        role="batch",
                        backend="mlx_lm",
                        messages=payload["messages"],
                        context_sources=(
                            observability.message_context_counts(
                                payload["messages"],
                                "document_web",
                            )
                        ),
                    )
                    try:
                        connect_started = time.monotonic()
                        with urllib.request.urlopen(
                            request,
                            timeout=900,
                        ) as response:
                            call_metrics.set_upstream_connect(
                                (time.monotonic() - connect_started) * 1000
                            )
                            result = json.loads(
                                response.read().decode("utf-8")
                            )

                    except urllib.error.HTTPError as exc:
                        call_metrics.fail("http_error")
                        body = exc.read().decode(
                            "utf-8",
                            errors="replace",
                        )

                        error_text = (
                            "MLX HTTP "
                            + str(exc.code)
                            + " in Chunk "
                            + str(index)
                            + ": "
                            + body
                        )

                        if (
                            is_metal_oom_error(error_text)
                            and part_tokens > 500
                        ):
                            next_tokens = max(
                                500,
                                part_tokens // 2,
                            )

                            smaller_parts = split_batch_part_for_oom(
                                part_text,
                                detected_type,
                                next_tokens,
                            )

                            if (
                                len(smaller_parts) <= 1
                            ):
                                raise RuntimeError(
                                    error_text
                                ) from exc

                            pending_parts = [
                                {
                                    "text": item,
                                    "tokens": next_tokens,
                                }
                                for item in smaller_parts
                            ] + pending_parts

                            with BATCH_LOCK:
                                jobs = load_batch_jobs()

                                if job_id in jobs:
                                    jobs[job_id]["oom_retries"] = (
                                        int(
                                            jobs[job_id].get(
                                                "oom_retries",
                                                0
                                            )
                                        ) + 1
                                    )

                                    jobs[job_id]["adaptive_chunk_tokens"] = (
                                        next_tokens
                                    )

                                    save_batch_jobs(jobs)

                            continue

                        raise RuntimeError(
                            error_text
                        ) from exc

                    except Exception as exc:
                        call_metrics.fail(type(exc).__name__)
                        raise

                    try:
                        choice = result["choices"][0]
                        transformed_part = choice["message"]["content"] or ""
                    except Exception as exc:
                        call_metrics.fail(type(exc).__name__)
                        raise RuntimeError(
                            f"Ungültige MLX-Antwort in Chunk {index}: {exc}"
                        )

                    call_metrics.finish(
                        usage=result.get("usage"),
                        output_text=transformed_part,
                        finish_reason=choice.get("finish_reason"),
                    )

                    transformed_parts.append(
                        transformed_part
                    )

                if detected_type == "json" and len(transformed_parts) > 1:
                    source_value = json.loads(working_chunk)
                    part_analysis = {"chunk_strategy": "json_object"}
                    if isinstance(source_value, list):
                        part_analysis["chunk_strategy"] = "json_array"
                    elif isinstance(source_value, dict):
                        list_keys = [
                            key
                            for key, value in source_value.items()
                            if isinstance(value, list)
                        ]
                        if list_keys:
                            list_key = max(
                                list_keys,
                                key=lambda key: len(source_value[key]),
                            )
                            part_analysis.update({
                                "chunk_strategy": "json_object_list",
                                "json_list_key": list_key,
                            })
                    transformed = assemble_batch_json(
                        transformed_parts,
                        part_analysis,
                    )
                else:
                    transformed = "\n".join(
                        part
                        for part in transformed_parts
                        if part
                    )

            checkpoint_path = batch_checkpoint_path(
                job_id,
                index,
            )

            temp_checkpoint = checkpoint_path.with_suffix(
                ".tmp"
            )

            checkpoint_content = transformed

            if (
                checkpoint_content and
                not checkpoint_content.endswith("\n")
            ):
                checkpoint_content += "\n"

            temp_checkpoint.write_text(
                checkpoint_content,
                encoding="utf-8",
            )

            temp_checkpoint.replace(
                checkpoint_path
            )

            chunk_duration = (
                time.time() -
                chunk_started_at
            )

            with BATCH_LOCK:
                jobs = load_batch_jobs()

                current_job = jobs[job_id]

                current_job["processed_chunks"] = index
                current_job["checkpoint_count"] = max(
                    int(current_job.get("checkpoint_count", 0)),
                    index,
                )
                current_job["last_chunk_seconds"] = chunk_duration

                previous_average = float(
                    current_job.get(
                        "average_chunk_seconds"
                    ) or 0
                )

                if index <= 1 or previous_average <= 0:
                    average = chunk_duration
                else:
                    average = (
                        (
                            previous_average *
                            (index - 1)
                        ) +
                        chunk_duration
                    ) / index

                current_job["average_chunk_seconds"] = average

                remaining = max(
                    0,
                    len(chunks) - index
                )

                current_job["eta_seconds"] = (
                    average *
                    remaining
                )

                current_job["current_chunk"] = None
                current_job["current_chunk_started_at"] = None

                if (
                    current_job.get(
                        "execution_mode",
                        "automatic",
                    ) == "controlled"
                    and index < len(chunks)
                ):
                    current_job["status"] = "paused"
                    current_job["waiting_for_user"] = True
                    current_job["resume_from_chunk"] = index + 1

                save_batch_jobs(jobs)

        # Assemble only fully checkpointed output.  A JSON array is rebuilt
        # from its independently valid array chunks so the original structure
        # remains valid instead of concatenating JSON documents.
        checkpoint_texts = [
            batch_checkpoint_path(job_id, index).read_text(encoding="utf-8")
            for index in range(1, len(chunks) + 1)
        ]
        if detected_type == "json":
            output_text = assemble_batch_json(
                checkpoint_texts,
                analysis,
            )
        else:
            output_text = "".join(checkpoint_texts)

        temporary_output = output_path.with_suffix(output_path.suffix + ".tmp")
        write_batch_text(
            temporary_output,
            output_text,
            encoding,
        )
        temporary_output.replace(output_path)

        with BATCH_LOCK:
            jobs = load_batch_jobs()
            if job_id in jobs:
                jobs[job_id]["output_name"] = output_path.name
                jobs[job_id]["output_size"] = output_path.stat().st_size
                jobs[job_id]["output_mime_type"] = "application/json" if output_path.suffix.lower() == ".json" else "text/plain"
                operations = set(instruction_plan.get("operations", []))
                if operations.intersection({"replace_emails", "replace_phone_numbers", "replace_names", "replace_addresses"}):
                    jobs[job_id]["pii_audit"] = deterministic_pii_audit(output_text)
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["finished_at"] = time.time()
            save_batch_jobs(jobs)

    except Exception as exc:
        with BATCH_LOCK:
            jobs = load_batch_jobs()

            if job_id in jobs:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["error"] = str(exc)
                jobs[job_id]["finished_at"] = time.time()
                jobs[job_id]["current_chunk"] = None
                jobs[job_id]["current_chunk_started_at"] = None
                jobs[job_id]["waiting_for_user"] = False
                jobs[job_id]["eta_seconds"] = None

                save_batch_jobs(jobs)

    finally:
        with BATCH_LOCK:
            jobs = load_batch_jobs()
            if job_id in jobs:
                jobs[job_id]["model_metrics"] = (
                    observability.trace_snapshot(trace_id)
                )
                save_batch_jobs(jobs)
        observability.reset_trace_id(trace_token)
        unregister_batch_worker(
            job_id
        )


@app.post("/api/batch/{job_id}/start")
@locked_batch_start
def start_batch_job(job_id: str):
    with BATCH_LOCK:
        jobs = load_batch_jobs()
        job = jobs.get(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Batch-Job nicht gefunden",
        )

    if batch_worker_is_alive(job_id):
        raise HTTPException(
            status_code=409,
            detail="Batch-Job läuft bereits",
        )

    # A persisted running state without a live worker means
    # that the agent or worker was interrupted.
    if job.get("status") == "running":
        with BATCH_LOCK:
            jobs = load_batch_jobs()

            if job_id in jobs:
                jobs[job_id]["status"] = "interrupted"
                jobs[job_id]["current_chunk"] = None
                jobs[job_id]["current_chunk_started_at"] = None

                save_batch_jobs(jobs)

    thread = threading.Thread(
        target=run_batch_transform_job,
        args=(job_id,),
        daemon=True,
        name=f"batch-{job_id}",
    )

    register_batch_worker(
        job_id,
        thread,
    )

    try:
        thread.start()

    except Exception:
        unregister_batch_worker(
            job_id
        )
        raise

    return {
        "ok": True,
        "job_id": job_id,
    }


# ============================================================
# Batch Upload
# ============================================================

from fastapi import UploadFile, File


MAX_UPLOAD_SIZE_MB = int(
    os.environ.get(
        "MAX_UPLOAD_SIZE_MB",
        "250",
    )
)

MAX_UPLOAD_SIZE_BYTES = (
    MAX_UPLOAD_SIZE_MB * 1024 * 1024
)


BATCH_UPLOAD_DIRECTORY = (
    Path.home() /
    ".config/mlx-web/batch/uploads"
)


@app.post("/api/batch/upload")
async def upload_batch_file(
    file: UploadFile = File(...)
):
    BATCH_UPLOAD_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    original_name = (
        Path(file.filename or "upload.bin")
        .name
    )

    suffix = Path(original_name).suffix

    target_name = (
        uuid.uuid4().hex[:12] +
        suffix
    )

    target_path = (
        BATCH_UPLOAD_DIRECTORY /
        target_name
    )

    size = 0

    try:
        with target_path.open("wb") as handle:
            while True:
                chunk = await file.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                size += len(chunk)

                if size > MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "Datei ist zu groß. "
                            f"Maximal erlaubt: "
                            f"{MAX_UPLOAD_SIZE_MB} MB"
                        ),
                    )

                handle.write(chunk)

    except BaseException:
        target_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    return {
        "ok": True,
        "original_name": original_name,
        "stored_name": target_name,
        "path": str(target_path),
        "size": size,
    }


@app.get("/api/batch/{job_id}/download")
def download_batch_output(job_id: str):
    with BATCH_LOCK:
        job = load_batch_jobs().get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch-Job nicht gefunden")
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail="Ausgabe ist noch nicht verfügbar")
    output_path = Path(job.get("output_path", ""))
    if not output_path.is_file():
        raise HTTPException(status_code=404, detail="Output-Datei nicht gefunden")
    return FileResponse(str(output_path), filename=output_path.name)


@app.post("/api/batch/{job_id}/pause")
def pause_batch_job(job_id: str):
    with BATCH_LOCK:
        jobs = load_batch_jobs()
        job = jobs.get(job_id)

        if not job:
            raise HTTPException(
                status_code=404,
                detail="Batch-Job nicht gefunden",
            )

        if job.get("status") != "running":
            raise HTTPException(
                status_code=409,
                detail="Nur laufende Jobs können pausiert werden",
            )

        job["status"] = "paused"
        jobs[job_id] = job
        save_batch_jobs(jobs)

    return {
        "ok": True,
        "job_id": job_id,
        "status": "paused",
    }


@app.post("/api/batch/{job_id}/resume")
def resume_batch_job(job_id: str):
    with BATCH_LOCK:
        jobs = load_batch_jobs()
        job = jobs.get(job_id)

        if not job:
            raise HTTPException(
                status_code=404,
                detail="Batch-Job nicht gefunden",
            )

        if job.get("status") != "paused":
            raise HTTPException(
                status_code=409,
                detail="Job ist nicht pausiert",
            )

        job["status"] = "running"
        job["waiting_for_user"] = False
        jobs[job_id] = job
        save_batch_jobs(jobs)

    return {
        "ok": True,
        "job_id": job_id,
        "status": "running",
    }


@app.post("/api/batch/{job_id}/automatic")
def automatic_batch_job(job_id: str):

    with BATCH_LOCK:

        jobs = load_batch_jobs()
        job = jobs.get(job_id)

        if not job:
            raise HTTPException(
                status_code=404,
                detail="Batch-Job nicht gefunden",
            )

        if job.get("status") not in {
            "queued",
            "paused",
            "running",
        }:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Job kann nicht auf automatische "
                    "Verarbeitung umgestellt werden"
                ),
            )

        job["execution_mode"] = "automatic"
        job["waiting_for_user"] = False

        if job.get("status") == "paused":
            job["status"] = "running"

        jobs[job_id] = job
        save_batch_jobs(jobs)

    return {
        "ok": True,
        "job_id": job_id,
        "status": "running",
        "execution_mode": "automatic",
    }


@app.post("/api/batch/{job_id}/cancel")
def cancel_batch_job(job_id: str):
    with BATCH_LOCK:
        jobs = load_batch_jobs()
        job = jobs.get(job_id)

        if not job:
            raise HTTPException(
                status_code=404,
                detail="Batch-Job nicht gefunden",
            )

        if job.get("status") not in {
            "queued",
            "running",
            "paused",
        }:
            raise HTTPException(
                status_code=409,
                detail="Job kann nicht mehr abgebrochen werden",
            )

        job["status"] = "cancelled"
        job["finished_at"] = time.time()

        jobs[job_id] = job
        save_batch_jobs(jobs)

    return {
        "ok": True,
        "job_id": job_id,
        "status": "cancelled",
    }


# =========================================================
# Agent V2 - controlled write actions with approval
# =========================================================

import time as _agent_time
import uuid as _agent_uuid


PENDING_AGENT_ACTIONS = {}
PENDING_AGENT_ACTIONS_LOCK = threading.Lock()
AGENT_APPROVAL_TTL = 300
ACTIVE_AGENT_RUNS = {}
ACTIVE_AGENT_RUNS_LOCK = threading.Lock()
AGENT_RUN_PROGRESS_TTL = 3600


def validate_agent_run_id(run_id):
    value=str(run_id or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9-]{16,64}", value):
        raise HTTPException(status_code=400, detail="Ungültige Agent-Run-ID")
    return value


def update_agent_run_progress(
    run_id,
    goal,
    status,
    steps,
    current_step=None,
    pending_action=None,
):
    now=_agent_time.time()
    progress={
        "run_id": run_id,
        "goal": str(goal or ""),
        "status": status,
        "steps": compact_agent_observations(list(steps or [])),
        "current_step": current_step,
        "pending_action": pending_action,
        "updated_at": now,
    }
    with ACTIVE_AGENT_RUNS_LOCK:
        expired=[
            key for key, entry in ACTIVE_AGENT_RUNS.items()
            if now - float(entry.get("updated_at") or 0) > AGENT_RUN_PROGRESS_TTL
        ]
        for key in expired:
            ACTIVE_AGENT_RUNS.pop(key, None)
        ACTIVE_AGENT_RUNS[run_id]=progress


class AgentApprovalRequest(BaseModel):
    approved: bool


def validate_agent_docker_target(target):
    target = str(target or "").strip()

    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}",
        target,
    ):
        raise ValueError(
            "Ungültiger Docker-Containername"
        )

    return target


def normalize_agent_conversation_context(context):
    if not isinstance(context, list):
        return []
    normalized=[]
    for entry in context[-8:]:
        if not isinstance(entry, dict):
            continue
        role=str(entry.get("role") or "").strip().lower()
        content=entry.get("content")
        if role not in {"user", "assistant"} or not isinstance(content,str):
            continue
        content=content.strip()
        if content:
            normalized.append({"role":role,"content":content[:2000]})
    return normalized


def compact_agent_observations(observations):
    """Keep iterative planning useful without reloading whole projects."""
    compact=[]
    internal_actions = {
        "code_read_search_anchor",
        "code_read_pagination",
    }

    for observation in observations:
        if observation.get("action") in internal_actions:
            continue

        entry=dict(observation)
        result=entry.get("result")
        if not isinstance(result, dict):
            compact.append(entry)
            continue
        result=dict(result)
        if entry.get("action") == "code_read" and isinstance(result.get("content"), str):
            content=result["content"]
            result["content"]=content[:16000]
            result["content_truncated"]=len(content) > 16000
        elif entry.get("action") == "code_files" and isinstance(result.get("files"), list):
            files=result["files"]
            result["files"]=files[:100]
            result["files_truncated"]=len(files) > 100
        elif entry.get("action") in {"code_patch", "code_diff"}:
            result["files"]=[
                {
                    "path": file.get("path"),
                    "operation": file.get("operation"),
                    "added": file.get("added"),
                    "removed": file.get("removed"),
                }
                for file in result.get("files", [])
                if isinstance(file, dict)
            ]
        elif entry.get("action") == "code_test" and isinstance(result.get("results"), list):
            result["results"]=[
                {
                    **test_result,
                    "output": str(test_result.get("output") or "")[:1000],
                }
                for test_result in result["results"][:50]
                if isinstance(test_result, dict)
            ]
        entry["result"]=result
        compact.append(entry)
    return compact


def ambiguous_delete_reference(goal, conversation_context):
    value=str(goal or "").strip().lower()
    delete_intent=any(marker in value for marker in (
        "lösche", "loesche", "entferne", "delete", "remove", "kann weg",
    ))
    vague_reference=any(marker in value for marker in (
        "das wieder", "die seite wieder", "die datei wieder", "dort wieder",
        "lösche das", "loesche das", "entferne das",
    ))
    if not delete_intent or not vague_reference:
        return False
    if re.search(r"[a-z0-9_./-]+\.[a-z0-9]{1,12}\b", value):
        return False
    return not normalize_agent_conversation_context(conversation_context)


def agent_choose_next_step_v2(
    goal,
    observations,
    max_steps=MAX_TOOL_STEPS,
    mode="diagnostic",
    conversation_context=None,
):
    mode = str(mode or "diagnostic").strip().lower()
    coding_mode = mode == "coding"

    if (
        not observations
        and mode in {"diagnostic", "orchestrator"}
        and _looks_like_disk_usage_request(goal)
    ):
        return {
            "action": "disk_usage",
            "reason": "Große Dateien und Ordner sicher analysieren",
            "options": {},
        }

    if coding_mode:
        role_context = """
Du bist der lokale Coding-Agent für den aktiven Code-Workspace.

Du darfst und sollst legitime Datei-Erstellungen und Änderungen über den
sicheren Patch-Workflow vorbereiten. Behaupte niemals, Dateien könnten
grundsätzlich nicht erstellt oder geändert werden, wenn der Auftrag den
aktiven Workspace betrifft.

Sicherheitsmodell:
- READ-Operationen dürfen automatisch ausgeführt werden.
- PREPARE-Operationen wie code_patch dürfen automatisch ausgeführt werden,
  weil sie keine echte Workspace-Datei verändern.
- WRITE-Operationen wie code_apply benötigen immer eine ausdrückliche
  Benutzerfreigabe.
""".strip()
        approval_context = """
Als einzige schreibende Aktion kannst du code_apply vorschlagen:

code_apply
- Wendet einen bereits vorbereiteten und geprüften Code-Patch an.
- Darf NIEMALS direkt ausgeführt werden.
- Benötigt vorher die ausdrückliche Zustimmung des Nutzers.
- "target" enthält ausschließlich die patch_id.
- Darf erst nach erfolgreichem code_diff und code_test vorgeschlagen werden.

Nach geprüftem Patch:
{
  "action": "request_approval",
  "operation": "code_apply",
  "target": "PATCH_ID",
  "reason": "Patch wurde geprüft und soll angewendet werden"
}
""".strip()
        patch_context = """
Für code_patch MUSST du strukturiertes JSON verwenden:

{
  "action": "code_patch",
  "reason": "Warum diese Änderung notwendig ist",
  "instruction": "Kurze Beschreibung der Änderung",
  "files": [
    {
      "path": "relativer/pfad/zur/datei.py",
      "operation": "CREATE | MODIFY | DELETE",
      "proposed_content": "VOLLSTÄNDIGER neuer Dateiinhalt"
    }
  ]
}

code_patch verändert den Workspace NICHT und benötigt keine Freigabe.
Für CREATE/MODIFY enthält proposed_content immer den vollständigen neuen
Inhalt, niemals nur einen Diff oder Ausschnitt. Für DELETE muss operation
explizit "DELETE" sein; proposed_content ist null oder leer.
Alle Dateien einer logisch zusammengehörigen Aufgabe gehören in EINEN
code_patch-Aufruf. Erzeuge nicht pro Datei einen eigenen Patch.
""".strip()
        mode_rules = """
Bei Coding-Aufträgen gilt zwingend:

1. Verwende ausschließlich den aktiven registrierten Workspace.
2. Untersuche bei Projektaufträgen zuerst gezielt die Struktur mit code_files.
   Ein leeres Ergebnis bedeutet Greenfield und ist kein Fehler. Plane dann
   eine zum Auftrag passende kleine Projektstruktur. Lade niemals blind das
   gesamte Projekt in den Kontext.
3. Erzeuge intern einen kurzen, anpassbaren Implementierungsplan. Du darfst
   ihn im JSON-Feld "plan" als kurze String-Liste mitsenden. Für triviale
   Ein-Datei-Aufträge genügt ein sehr kurzer Plan.
4. Nutze progressive Discovery: Dateiliste, gezielte Suche, relevante Dateien
   lesen, bei neu entdeckten Referenzen weiter lesen, dann erst patchen.
5. Für CREATE einer eindeutig neuen Datei darfst du direkt code_patch verwenden.
   code_read auf die noch nicht existierende Zieldatei ist nicht erlaubt.
6. Für MODIFY musst du jede vorhandene Zieldatei zuerst mit code_read lesen.
7. Für DELETE musst du die vorhandene Datei zuerst mit code_read lesen oder
   ihre Existenz eindeutig mit code_files prüfen. Verwende anschließend
   code_patch mit operation="DELETE"; niemals rm oder Shell-Schreibbefehle.
8. Bei Folgeaufträgen darfst du einen Dateinamen aus dem bereitgestellten
   Gesprächskontext übernehmen, wenn genau eine Datei eindeutig gemeint ist.
   Ist das Ziel mehrdeutig, stelle in einer final-Antwort eine Rückfrage und
   erzeuge insbesondere keinen DELETE-Patch.
9. Wenn Projektkonventionen für CREATE relevant sind, darfst du vorher mit
   code_files/code_search suchen und passende vorhandene Dateien lesen.
10. Erhalte Architektur, Stil, Namensgebung und Framework-Konventionen des
    Projekts. Bevorzuge minimal-invasive Änderungen. Füge keine neue Dependency
    hinzu, wenn die Aufgabe ohne sie vernünftig lösbar ist, und installiere
    niemals Dependencies.
11. Kombiniere alle logisch zusammengehörigen CREATE-/MODIFY-/DELETE-Änderungen
    in genau einem Multi-File-Change-Set. Splitte nur große, unabhängig
    testbare Einheiten mit sachlichem Grund.
12. Nach code_patch verwende die zurückgegebene patch_id zuerst mit code_diff
   und danach mit code_test.
13. Erst nach erfolgreichem code_diff und code_test fordere die Freigabe für
   code_apply an.
14. Verwende niemals shell_read oder ein anderes Shell-Tool, um Dateien zu
   erstellen, zu überschreiben oder zu löschen.
15. Schreibe niemals außerhalb des aktiven Workspaces und umgehe niemals
   _safe(), Patch-Konfliktprüfungen oder das Approval-System.
16. Wenn der Nutzer CREATE, MODIFY oder DELETE verlangt, bereite einen Patch vor,
   statt die Aufgabe mit einem Hinweis auf READ-ONLY-Zugriff abzulehnen.
17. Keine Binärdateien über proposed_content erzeugen oder verändern. Melde
    benötigte Bilder, Fonts, PDFs oder Archive transparent.
18. Nach freigegebenem code_apply wird die vorhandene verify_change-Prüfung
    ausgeführt; melde Erfolg nur bei verified=true.

19. EVIDENCE-GRUNDREGEL: Behaupte einen Defekt, eine Schwäche, ein fehlendes
    Sicherheitsmerkmal oder ein Robustheitsproblem nur dann als Tatsache,
    wenn es durch tatsächlich gelesenen Code direkt belegt ist.

20. Wenn eine Schlussfolgerung von einem Caller, Helper, einer Konfiguration,
    einem externen Kommando oder anderem noch nicht gelesenen Code abhängt,
    untersuche diese Evidence zuerst mit code_search/code_read. Falls sie
    innerhalb des Auftrags nicht verifiziert werden kann, kennzeichne die
    Aussage ausdrücklich als unbestätigt oder mögliche Fragestellung.

21. Schließe niemals allein aus dem Fehlen einer Funktionalität im aktuell
    gelesenen Ausschnitt, dass diese Funktionalität im Gesamtsystem fehlt.

22. Trenne in Analyse und finaler Antwort strikt zwischen:
    - direkt beobachteten Fakten,
    - daraus abgeleiteten Schlussfolgerungen,
    - unbestätigten Risiken,
    - optionalen Empfehlungen.

23. Generische Best Practices sind keine nachgewiesenen Defekte. Empfehle
    Logging, Rollback, Backoff, Health-Checks, Prozessüberwachung,
    Idempotenz, zusätzliche Validierung oder ähnliche Maßnahmen nur dann
    als konkrete Verbesserung, wenn die gelesene Evidence einen relevanten
    Schwachpunkt dafür zeigt.

24. Bevor du fehlendes Locking, fehlende Validierung, fehlende
    Fehlerbehandlung, fehlende Health-Checks, fehlenden Rollback,
    fehlende Prozessüberwachung oder fehlende Idempotenz behauptest,
    suche gezielt nach relevanten Callern, Helpern und Kontrollpfaden.

25. Widersprich niemals bereits gelesener Evidence. Wenn neue Evidence eine
    frühere Annahme widerlegt, verwirf die Annahme und verwende ausschließlich
    den verifizierten Stand in der finalen Antwort.
""".strip()
    elif mode == "orchestrator":
        role_context = """
Du bist der autonome lokale MLX nobby-Orchestrator.

WICHTIG:
- "orchestrator" ist dein Betriebsmodus und KEIN Tool.
- Gib niemals {"action":"orchestrator"} zurück.
- Wähle als action ausschließlich ein tatsächlich verfügbares Tool,
  "final" oder eine ausdrücklich erlaubte Approval-Aktion.

Deine Aufgabe ist es, komplexe Nutzerziele selbstständig in sinnvolle
Teilschritte zu zerlegen und dafür mehrere vorhandene lokale Fähigkeiten
miteinander zu kombinieren.

Du bist kein einzelner Diagnose-, Coding- oder Research-Agent, sondern die
Koordinationsschicht darüber.

Du darfst alle verfügbaren READ-Tools selbstständig kombinieren:
Webrecherche, lokale Wissensbasis, Code-Workspace und Systemdiagnose.

Zusätzlich darfst du komplexe, klar abgrenzbare Teilschritte an
Spezialagenten delegieren.

Dafür steht dir ausschließlich im Orchestrator-Modus die interne Aktion
"delegate_agent" zur Verfügung.

Erlaubte Spezialagenten:

- research
  Für Webrecherche, Quellenanalyse und externe Informationen.

- diagnostic
  Für lokale Systemanalyse, Prozesse, Logs und technische Diagnose.

- coding_analysis
  Für reine READ-ONLY-Analyse des aktiven Code-Workspaces.

Format:

{
  "action": "delegate_agent",
  "agent": "research | diagnostic | coding_analysis",
  "goal": "Konkretes, eigenständig bearbeitbares Teilziel",
  "reason": "Warum dieser Spezialagent sinnvoll ist"
}

WICHTIG:
- delegate_agent ist KEIN normales READ-Tool.
- Nur der Orchestrator darf delegate_agent verwenden.
- Delegierte Spezialagenten dürfen niemals selbst weitere Agenten delegieren.
- coding_analysis darf ausschließlich analysieren und niemals code_patch,
  code_apply oder andere Änderungen vorbereiten.
- Delegiere nur echte Teilaufgaben. Für einen einzelnen einfachen Tool-Aufruf
  verwende weiterhin direkt das passende READ-Tool.

SUBAGENT-QUALITÄT:

Nach einer Delegation kann das Ergebnis ein Feld "quality" enthalten.

Wenn dort

  "needs_verification": true

steht, behandle das Ergebnis nicht als abschließend verifiziert.

WICHTIG:
Du darfst in diesem Zustand NICHT mit action="final" abschließen.
Du musst zuerst eine sinnvolle Verifikation versuchen.

Ein späterer Report desselben Spezialagenten mit
"evidence_sufficient": true
kann die offene Verifikation auflösen.

Wenn mehrere sinnvolle Verifikationsversuche ausgeschöpft wurden und
weiterhin keine ausreichende Evidence verfügbar ist, darfst du mit den
vorhandenen Observations abschließen. Kennzeichne dann ausdrücklich,
dass die gewünschte Verifikation nicht erreicht wurde. Erfinde keine
fehlende Evidence und behaupte keine nicht bestätigten Fakten.

Prüfe dann, ob eine weitere sinnvolle Untersuchung möglich ist, zum Beispiel:

- Research erneut mit präziserem Teilziel,
- einen anderen Spezialagenten verwenden,
- eine konkrete Quelle gezielt untersuchen,
- lokale Evidence zusätzlich prüfen.

Wenn

  "evidence_sufficient": true

ist, darfst du die Findings grundsätzlich für deine Synthese verwenden.

Vermeide unnötige Wiederholungen. Eine Verifikation soll nur erfolgen,
wenn sie realistisch zusätzliche Evidence liefern kann.

Du arbeitest zielorientiert:
ZIEL -> PLAN -> TOOL -> OBSERVATION -> PLAN ANPASSEN -> TOOL -> SYNTHESE.

Du darfst keine echte Änderung am System oder Workspace autonom durchführen.
""".strip()

        approval_context = ""
        patch_context = ""

        mode_rules = """
Im Orchestrator-Modus gilt:

1. Erstelle zu Beginn intern einen kurzen Gesamtplan.
2. Zerlege komplexe Ziele in logisch getrennte Teilschritte.
3. Wähle für jeden Teilschritt das passendste READ-Tool.
4. Kombiniere unterschiedliche Fähigkeiten, wenn das Ziel es verlangt.
5. Verwende Websuche nur, wenn aktuelle oder externe Informationen nötig sind.

6. Bei technischer Webrecherche gilt folgende Quellenhierarchie:
   - zuerst offizielle Dokumentation des Projekts oder Herstellers,
   - danach offizielles GitHub-Repository, Releases, Issues und Discussions,
   - danach Quellen direkt beteiligter Maintainer oder Organisationen,
   - Drittanbieter-Blogs, Tutorials und Foren nur ergänzend.
   Bevorzuge Primärquellen gegenüber Zusammenfassungen und SEO-Artikeln.

7. Bei Fragen nach aktuellen Best Practices, Versionen oder Entwicklungen:
   - erfinde keine Jahreszahlen für Suchanfragen,
   - verwende eine Jahreszahl nur, wenn sie sicher aus dem Kontext bekannt
     oder für das Nutzerziel ausdrücklich erforderlich ist,
   - bevorzuge aktuelle Releases, offizielle Dokumentation und aktuelle
     Repository-Informationen gegenüber älteren Artikeln.

8. Wenn Web-Ergebnisse für eine technische Schlussfolgerung wesentlich sind,
   öffne nach der Suche mindestens eine geeignete Primärquelle mit fetch_url,
   sofern eine Primärquelle in den Treffern verfügbar ist.

9. Behaupte niemals, eine Quelle bestätige, empfehle oder beweise etwas,
   das aus dem tatsächlich geladenen Inhalt nicht hervorgeht.
6. Verwende knowledge_search für lokale Wissensbestände.
7. Verwende code_files, code_search und code_read für den aktiven Code-Workspace.
8. Bei code_read MUSS ein gewünschter Zeilenbereich direkt in "query" stehen.
   Beispiele:
   - {"action":"code_read","query":"agent/app.py"}
   - {"action":"code_read","query":"agent/app.py:242-500"}
   - {"action":"code_read","query":"agent/app.py:501-740"}
   Schreibe Zeilenbereiche NICHT nur in "instruction".
9. Wenn ein code_read nur einen Teil einer Datei liefert und du weiterlesen musst,
   verwende beim nächsten Aufruf einen neuen, nicht überlappenden Zeilenbereich.
   Wiederhole niemals denselben code_read-Bereich mehrfach.
8. Verwende system_status, process_usage, logs_query oder shell_read für lokale Diagnose.
9. Bewerte nach jeder Observation, ob der Plan angepasst werden muss.
10. Wiederhole keine Abfrage ohne sachlichen Grund.
11. Beende die Aufgabe erst, wenn genügend Informationen für das Nutzerziel vorliegen.
12. Erfinde niemals Ergebnisse fehlender Tools.
13. code_patch und code_apply stehen im Orchestrator-Modus nicht zur Verfügung.
14. Wenn eine echte Änderung nötig wäre, beschreibe sie in der Abschlussantwort,
    führe sie aber nicht selbst aus.
15. Führe Ergebnisse verschiedener Quellen und Fähigkeiten in einer gemeinsamen
    Abschlussantwort zusammen.
""".strip()

    elif mode == "research":
        role_context = """
Du bist ein lokaler Research-Agent. Du recherchierst mit den verfügbaren
READ-Tools und veränderst weder Dateien noch Dienste.
""".strip()
        approval_context = ""
        patch_context = ""
        mode_rules = """
Im Research-Modus gilt:
- Nur READ-Tools selbstständig ausführen.
- code_patch, code_apply und docker_restart weder aufrufen noch vorschlagen.
- Für Webrecherche search_web und fetch_url verwenden und Quellen nennen.
- fetch_url lädt lange Textquellen kontrolliert in Ausschnitten.
- Wenn ein erfolgreicher fetch_url-Aufruf "truncated": true liefert,
  wurde die Quelle NICHT vollständig gelesen.
- "next_offset": N gibt den Startpunkt des nächsten Ausschnitts an.
- Wenn die für das Nutzerziel benötigte Evidence im aktuellen Ausschnitt
  noch nicht gefunden wurde und "truncated": true ist, lies dieselbe URL
  mit "instruction": "offset=N" weiter, wobei N exakt dem gelieferten
  next_offset entspricht.
- Stoppe das Weiterlesen sofort, sobald die benötigte Evidence gefunden
  wurde oder "truncated": false erreicht ist.
- Behaupte niemals, eine Quelle vollständig geprüft zu haben, solange
  der zuletzt geladene relevante Ausschnitt "truncated": true enthält.
""".strip()
    else:
        role_context = """
Du bist ein lokaler technischer Diagnose-Agent auf einem Mac.

Du darfst ausschließlich READ-Operationen automatisch ausführen. code_patch
und code_apply stehen in diesem Modus nicht zur Verfügung. Verändere keine
Dateien und verwende keine Shell-Schreiboperationen.
""".strip()
        approval_context = """
Wenn eine technische Diagnose eindeutig einen Container-Neustart erfordert,
kannst du ausschließlich diese zustandsverändernde Aktion zur Freigabe
vorschlagen:

{
  "action": "request_approval",
  "operation": "docker_restart",
  "target": "open-webui",
  "reason": "Konkrete technische Begründung"
}

docker_restart darf niemals direkt ausgeführt werden und benötigt die
ausdrückliche Zustimmung des Nutzers.
""".strip()
        patch_context = ""
        mode_rules = """
Im Diagnose-Modus gilt:
- Nur READ-Tools selbstständig ausführen.
- code_patch und code_apply weder aufrufen noch vorschlagen.
- Keine Dateien erstellen, verändern oder löschen.
- Keine generischen Shell-Schreibbefehle verwenden.
- Bei Fragen nach der höchsten Prozess-/App-Last zuerst process_usage nutzen
  und CPU sowie RAM/RSS getrennt auswerten. Niemals einen künstlichen
  universellen "Systemverbrauch" berechnen.
- Bei Fragen nach großen Dateien, Ordnergrößen oder belegtem Speicherplatz
  zuerst disk_usage verwenden. Dafür niemals du/find/sort über shell_read
  kombinieren.
""".strip()

    conversation_context = normalize_agent_conversation_context(
        conversation_context
    )
    conversation_block = (
        "LETZTER GESPRÄCHSKONTEXT (nur zur Referenzauflösung):\n"
        + json.dumps(conversation_context, ensure_ascii=False, indent=2)
        if conversation_context
        else "LETZTER GESPRÄCHSKONTEXT: keiner"
    )

    system_prompt = f"""
{role_context}

Du arbeitest iterativ:

PLAN -> TOOL -> OBSERVATION -> PLAN -> ...

{agent_tool_description(include_prepare=coding_mode)}

{approval_context}

Für einen automatisch erlaubten Tool-Aufruf:

{{
  "action": "tool_name",
  "reason": "Warum dieses Tool jetzt sinnvoll ist",
  "query": "konkreter Diagnosebefehl oder Suchtext"
}}

{patch_context}

Wenn die Untersuchung abgeschlossen ist:

{{
  "action": "final",
  "answer": "Klare Diagnose bzw. Abschlussantwort"
}}

Regeln:

- Antworte ausschließlich als JSON.
- Erfinde keine Tool-Ergebnisse.
- Nutze nur vorhandene Observations.
- Pro Schritt genau eine Aktion.
- Keine direkte Shell-Schreibaktion.
- Kein sudo.
- Kein rm.
- Kein kill oder pkill.
- Kein docker stop, rm oder compose down.
- Zustandsverändernde Aktionen ausschließlich über request_approval.

- Nutze shell_read bei passenden lokalen Diagnose-, Inventar- und Systemfragen aktiv und selbstständig.
- Nutze für Speicherplatzanalysen ausschließlich disk_usage. Wenn der Scan
  partial=true liefert, fasse die tatsächlich gefundenen Einträge zusammen
  und nenne die Warnungen knapp.
- Gib nach einem einzelnen erfolgreichen Diagnosebefehl nicht vorschnell auf, wenn mehrere Datenquellen für eine vollständige Antwort sinnvoll sind.
- Kombiniere bei Bedarf mehrere READ-ONLY-Abfragen und führe deren Ergebnisse anschließend zusammen.
- Wenn ein READ-ONLY-Befehl fehlschlägt oder keine ausreichenden Daten liefert, probiere eine andere erlaubte READ-ONLY-Methode.

{mode_rules}

Bei Fragen nach installierten Programmen oder Software auf macOS:
1. Prüfe /Applications mit shell_read, z. B. "ls /Applications".
2. Prüfe zusätzlich den Benutzerordner ~/Applications, falls vorhanden.
3. Nutze "system_profiler SPApplicationsDataType", wenn eine vollständigere macOS-Anwendungsliste hilfreich ist.
4. Prüfe Homebrew mit "brew list --cask" für GUI-Anwendungen.
5. Prüfe bei Bedarf zusätzlich "brew list" bzw. "brew leaves" für Kommandozeilen-Pakete.
6. Führe die Ergebnisse zusammen, entferne offensichtliche Duplikate und unterscheide nach Möglichkeit zwischen macOS-Apps, Homebrew-Casks und CLI-Paketen.
7. Verändere dabei nichts am System.

Bei allgemeinen Systemdiagnosen:
- beginne mit den relevantesten READ-ONLY-Abfragen,
- benutze weitere erlaubte Quellen, wenn das erste Ergebnis die Frage nicht vollständig beantwortet,
- fasse technische Rohdaten für den Benutzer verständlich zusammen,
- erfinde keine Werte, die nicht aus den Tool-Ergebnissen hervorgehen.

- Nach jeder ausgeführten Änderung muss eine Observation
  "verify_change" vorhanden sein.
- Eine Änderung darf nur dann als erfolgreich bezeichnet werden,
  wenn verify_change den Wert verified=true enthält.
- Bei verified=false untersuche die Ursache weiter und melde
  niemals fälschlich Erfolg.
- Wenn der Nutzer eine Aktion abgelehnt hat, fordere dieselbe
  Aktion nicht erneut an, außer neue technische Erkenntnisse
  rechtfertigen dies eindeutig.
- Maximal {max_steps} Schritte.
""".strip()

    answer = observed_agent_llm(
        "agent.plan",
        [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": (
                    "NUTZERZIEL:\n"
                    + goal
                    + "\n\n"
                    + conversation_block
                    + "\n\n"
                    + "BISHERIGE OBSERVATIONS:\n"
                    + json.dumps(
                        compact_agent_observations(observations),
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
            },
        ],
        max_tokens=12000 if coding_mode else 1000,
        temperature=0.05,
    )

    try:
        return parse_agent_json(answer)

    except ValueError as exc:
        print(
            "[agent-json] initial parse failed:",
            repr(str(exc)),
            flush=True,
        )
        print(
            "[agent-json] raw answer:",
            repr(str(answer or "")[:12000]),
            flush=True,
        )

    # Perform exactly one controlled format repair.
    # Do not execute an action until parsing succeeds.
        repaired_answer = observed_agent_llm(
            "agent.plan_repair",
            [
                {
                    "role": "system",
                    "content": (
                        "Du reparierst ausschließlich das JSON-Format einer "
                        "Agent-Antwort. Gib exakt EIN gültiges JSON-Objekt "
                        "zurück. Kein Markdown, keine Erklärung und kein Text "
                        "vor oder nach dem JSON. Verändere die beabsichtigte "
                        "Aktion nicht und erfinde keine Tool-Ergebnisse. "
                        "Erlaubte Grundformen sind "
                        '{"action":"TOOL","reason":"...","query":"..."} '
                        "oder "
                        '{"action":"final","answer":"..."}.'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Repariere diese Agent-Antwort zu gültigem JSON:\n\n"
                        + str(answer or "")[:8000]
                    ),
                },
            ],
            max_tokens=12000 if coding_mode else 1600,
            temperature=0.0,
        )

        try:
            return parse_agent_json(repaired_answer)

        except ValueError as repair_exc:
            print(
                "[agent-json] repair parse failed:",
                repr(str(repair_exc)),
                flush=True,
            )
            print(
                "[agent-json] repaired answer:",
                repr(str(repaired_answer or "")[:12000]),
                flush=True,
            )
            raise

def validate_agent_patch_id(target):
    target = str(target or "").strip()

    if not re.fullmatch(r"[a-fA-F0-9]{16}", target):
        raise ValueError(
            "Ungültige Patch-ID"
        )

    return target


def create_agent_approval(
    goal,
    observations,
    step,
    mode,
    operation,
    target,
    reason,
    conversation_context=None,
):
    mode = str(mode or "diagnostic").strip().lower()

    if operation not in {
        "docker_restart",
        "code_apply",
    }:
        raise ValueError(
            f"Nicht freigegebene Agent-Aktion: {operation}"
        )

    if operation == "code_apply" and mode != "coding":
        raise ValueError(
            "code_apply ist ausschließlich im Coding-Modus verfügbar"
        )
    if operation == "docker_restart" and mode != "diagnostic":
        raise ValueError(
            "docker_restart ist ausschließlich im Diagnose-Modus verfügbar"
        )

    if operation == "docker_restart":
        target = validate_agent_docker_target(target)

    elif operation == "code_apply":
        target = validate_agent_patch_id(target)

    # Approve only a patch that actually exists.
        patch_state = code_workspaces.diff(target)
        if patch_state.get("status") != "proposed":
            raise ValueError("code_apply benötigt einen vorgeschlagenen Patch")

    # Diff and test must exist as successful, ordered observations
    # for this exact patch.
        diff_step = None
        test_step = None
        test_result = None

        for index, observation in enumerate(observations):
            if observation.get("status") != "completed":
                continue

            if str(observation.get("query") or "").strip() != target:
                continue

            if observation.get("action") == "code_diff":
                result = observation.get("result") or {}
                if result.get("patch_id") == target:
                    diff_step = index

            if observation.get("action") == "code_test":
                result = observation.get("result") or {}
                checks_run = result.get("checks_run")
                if (
                    result.get("patch_id") == target
                    and result.get("passed") is True
                    and result.get("test_status") == "passed"
                    and type(checks_run) is int
                    and checks_run > 0
                ):
                    test_step = index
                    test_result = result

        if (
            diff_step is None
            or test_step is None
            or diff_step >= test_step
        ):
            raise ValueError(
                "code_apply benötigt vorher code_diff und danach einen "
                "erfolgreichen code_test"
            )

    approval_id = _agent_uuid.uuid4().hex
    now = _agent_time.time()

    pending = {
        "id": approval_id,
        "operation": operation,
        "target": target,
        "reason": str(reason or "").strip(),
        "goal": goal,
        "mode": mode,
        "conversation_context": normalize_agent_conversation_context(
            conversation_context
        ),
        "observations": observations,
        "step": step,
        "created_at": now,
        "expires_at": now + AGENT_APPROVAL_TTL,
    }

    with PENDING_AGENT_ACTIONS_LOCK:
        PENDING_AGENT_ACTIONS[approval_id] = pending

    return {
        "approval_id": approval_id,
        "operation": operation,
        "target": target,
        "reason": pending["reason"],
        "expires_in": AGENT_APPROVAL_TTL,
        **({
            "change_set_id": patch_state.get("change_set_id", target),
            "summary": patch_state.get("summary", {}),
            "files": [
                {
                    "path": entry.get("path"),
                    "operation": entry.get("operation"),
                }
                for entry in patch_state.get("files", [])
            ],
            "tests": {
                "passed": bool((test_result or {}).get("passed")),
                "test_status": (test_result or {}).get("test_status"),
                "checks_run": (test_result or {}).get("checks_run", 0),
                "results": len((test_result or {}).get("results", [])),
            },
        } if operation == "code_apply" else {}),
    }


def execute_agent_approved_action(pending):
    operation = pending["operation"]
    target = pending["target"]

    if operation == "code_apply":
        patch_id = validate_agent_patch_id(target)

        result = code_workspaces.apply(
            patch_id,
            approved=True,
        )

        return {
            "operation": operation,
            "target": patch_id,
            "returncode": 0,
            "stdout": "Patch erfolgreich angewendet",
            "stderr": "",
            "apply_result": result,
        }

    if operation != "docker_restart":
        raise ValueError(
            "Nicht freigegebene Agent-Aktion"
        )

    target = validate_agent_docker_target(target)

    result = subprocess.run(
        [
            "docker",
            "restart",
            target,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )

    return {
        "operation": operation,
        "target": target,
        "returncode": result.returncode,
        "stdout": (result.stdout or "")[-10000:],
        "stderr": (result.stderr or "")[-10000:],
    }


def orchestrator_required_evidence(goal):
    """Determine required capability groups from the user goal."""

    value = str(goal or "").lower()

    web_required = any(marker in value for marker in (
        "internet",
        "web",
        "online",
        "aktuell",
        "aktuelle",
        "aktuellen",
        "recherchiere",
        "recherchieren",
        "webrecherche",
        "best practices",
        "best-practices",
        "externe quelle",
        "externe quellen",
        "offizielle quelle",
        "offiziellen quelle",
        "offizielle dokumentation",
        "primärquelle",
        "primaerquelle",
    ))

    # Require local code evidence only when the user goal actually
    # concerns the active local workspace.
    explicit_local_code = any(marker in value for marker in (
        "lokaler code",
        "lokalen code",
        "lokale codebasis",
        "lokaler workspace",
        "lokalen workspace",
        "mein code",
        "meinen code",
        "unser code",
        "unseren code",
        "mein projekt",
        "meinem projekt",
        "unser projekt",
        "unserem projekt",
        "workspace",
        "lokale datei",
        "lokalen dateien",
        "lokale dateien",
        "im projekt",
        "im workspace",
    ))

    generic_code_request = any(marker in value for marker in (
        "quellcode analys",
        "code analys",
        "code prüfen",
        "code pruefen",
        "code untersuch",
        "code durchsuchen",
        "implementierung prüfen",
        "implementierung pruefen",
    ))

    code_required = explicit_local_code or generic_code_request

    knowledge_required = any(marker in value for marker in (
        "wissensbasis",
        "knowledge base",
        "rag",
        "lokales wissen",
        "lokale wissensbasis",
    ))

    return {
        "web": web_required,
        "code": code_required,
        "knowledge": knowledge_required,
    }

def orchestrator_observed_evidence(observations):
    """
    Determine evidence that was actually observed.

    Include both direct orchestrator tool calls and successfully completed
    tool steps from delegated specialist agents.
    """

    actions = set()

    def collect(entries):
        for item in entries or []:
            if not isinstance(item, dict):
                continue

            if item.get("status") != "completed":
                continue

            action = str(
                item.get("action") or ""
            ).strip()

            if action:
                actions.add(action)

            # Orchestrator v2:
            # include evidence from successful subagents.
            if action == "delegate_agent":
                result = item.get("result")

                if not isinstance(result, dict):
                    continue

                if result.get("status") not in {
                    "completed",
                    "max_steps",
                }:
                    continue

                child_steps = result.get("steps")

                if isinstance(child_steps, list):
                    collect(child_steps)

    collect(observations)

    return {
        "web": bool(
            actions
            & {
                "web_search",
                "search_web",
                "fetch_url",
            }
        ),
        "code": bool(
            actions
            & {
                "code_files",
                "code_search",
                "code_read",
            }
        ),
        "knowledge": (
            "knowledge_search" in actions
        ),
    }


def orchestrator_missing_evidence(goal, observations):
    required = orchestrator_required_evidence(goal)
    observed = orchestrator_observed_evidence(observations)

    return [
        capability
        for capability, needed in required.items()
        if needed and not observed.get(capability, False)
    ]


def normalize_delegate_goal(value):
    value = str(value or "").strip().lower()
    value = " ".join(value.split())
    return value[:1000]


def orchestrator_delegate_attempts(observations, agent_name):
    """
    Count delegations already run for the same specialist agent.
    """
    agent_name = str(agent_name or "").strip().lower()

    count = 0

    for item in observations or []:
        if not isinstance(item, dict):
            continue

        if item.get("status") != "completed":
            continue

        if str(item.get("action") or "").strip() != "delegate_agent":
            continue

        if str(item.get("agent") or "").strip().lower() == agent_name:
            count += 1

    return count


def orchestrator_duplicate_delegation(
    observations,
    agent_name,
    delegate_goal,
):
    """
    Detect identical or effectively identical delegations.
    """
    agent_name = str(agent_name or "").strip().lower()
    goal_norm = normalize_delegate_goal(delegate_goal)

    if not goal_norm:
        return False

    for item in observations or []:
        if not isinstance(item, dict):
            continue

        if item.get("status") != "completed":
            continue

        if str(item.get("action") or "").strip() != "delegate_agent":
            continue

        if str(item.get("agent") or "").strip().lower() != agent_name:
            continue

        previous_goal = normalize_delegate_goal(
            item.get("goal")
        )

        if previous_goal == goal_norm:
            return True

    return False


def orchestrator_unresolved_subagent_quality(observations):
    """
    Determine unresolved quality issues from delegated specialist agents.

    A later successful report from the same agent with
    evidence_sufficient=true resolves the open state.
    """
    state = {}

    for item in observations or []:
        if not isinstance(item, dict):
            continue

        if item.get("status") != "completed":
            continue

        if str(item.get("action") or "").strip() != "delegate_agent":
            continue

        agent_name = str(
            item.get("agent") or ""
        ).strip().lower()

        if not agent_name:
            continue

        result = item.get("result")
        if not isinstance(result, dict):
            continue

        quality = result.get("quality")
        if not isinstance(quality, dict):
            continue

        needs_verification = bool(
            quality.get("needs_verification")
        )

        evidence_sufficient = bool(
            quality.get("evidence_sufficient")
        )

        if needs_verification:
            state[agent_name] = {
                "agent": agent_name,
                "confidence": quality.get("confidence"),
                "reason": str(
                    quality.get("reason")
                    or "Subagent-Evidence benötigt weitere Verifikation."
                ).strip(),
            }

        elif evidence_sufficient:
            state.pop(agent_name, None)

    return list(state.values())


def coding_evidence_contract(observations):
    """
    Deterministic summary of what completed coding observations can prove.
    This constrains the final LLM synthesis without trying to parse claims.
    """
    completed_actions = {
        str(item.get("action") or "").strip()
        for item in observations
        if isinstance(item, dict)
        and item.get("status") == "completed"
    }

    evidence = []

    if "code_files" in completed_actions:
        evidence.append(
            "code_files proves only that workspace file metadata/listing was inspected."
        )

    if "code_search" in completed_actions:
        evidence.append(
            "code_search proves only that matching workspace locations were searched."
        )

    if "code_read" in completed_actions:
        evidence.append(
            "code_read proves that returned source code was inspected; "
            "it does NOT prove runtime behavior or successful execution."
        )

    if "code_patch" in completed_actions:
        evidence.append(
            "code_patch proves only that a proposed patch was prepared; "
            "it does NOT prove that workspace files were changed."
        )

    if "code_diff" in completed_actions:
        evidence.append(
            "code_diff proves only that the prepared patch diff was inspected."
        )

    if "code_test" in completed_actions:
        evidence.append(
            "code_test may support test-result claims only to the extent explicitly "
            "shown by its returned test results."
        )

    verified_change = any(
        isinstance(item, dict)
        and item.get("status") == "completed"
        and item.get("action") == "verify_change"
        and isinstance(item.get("result"), dict)
        and item.get("result", {}).get("verified") is True
        for item in observations
    )

    if verified_change:
        evidence.append(
            "verify_change with verified=true proves that the applied change passed "
            "the configured post-apply verification."
        )
    else:
        evidence.append(
            "No completed verify_change with verified=true exists. "
            "Do NOT claim that a change was successfully applied and verified."
        )

    if "code_test" not in completed_actions:
        evidence.append(
            "No completed code_test exists. Do NOT claim that tests were run or passed."
        )

    return evidence


def coding_final_answer_requires_repair(answer, observations):
    """
    Detect affirmative strong coding claims that are not supported by completed
    evidence. Explicit uncertainty/negation must not trigger the gate.
    """
    value = str(answer or "").lower()

    completed_actions = {
        str(item.get("action") or "").strip()
        for item in observations
        if isinstance(item, dict)
        and item.get("status") == "completed"
    }

    has_code_test = "code_test" in completed_actions

    has_verified_change = any(
        isinstance(item, dict)
        and item.get("status") == "completed"
        and item.get("action") == "verify_change"
        and isinstance(item.get("result"), dict)
        and item.get("result", {}).get("verified") is True
        for item in observations
    )

    reasons = []

    # Evaluate one sentence at a time so negative statements such as
    # "The code cannot be guaranteed to run without errors" are not
    # treated as positive claims about functionality.
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", value)
        if sentence.strip()
    ]

    def is_explicitly_uncertain(sentence):
        uncertainty_markers = (
            "nicht getestet",
            "nicht ausgeführt",
            "nicht verifiziert",
            "nicht bestätigt",
            "nicht garantiert",
            "kann nicht garantiert",
            "kann nicht bestätigt",
            "lässt sich nicht bestätigen",
            "lässt sich nicht verifizieren",
            "keine tests",
            "kein test",
            "keine verifikation",
            "keine garantie",
            "nicht möglich",
            "nicht beurteilt",
            "nicht geprüft",
            "ohne laufzeittest",
            "ohne test",
        )
        return any(marker in sentence for marker in uncertainty_markers)

    if not has_code_test:
        affirmative_runtime_patterns = (
            r"\b(?:der|die|das|dieser|diese|dieses)\b.{0,80}\b"
            r"(?:funktioniert korrekt|funktioniert einwandfrei|"
            r"technisch funktionsfähig|strukturell funktionsfähig|"
            r"ist fehlerfrei|sind fehlerfrei|"
            r"ist korrekt implementiert|sind korrekt implementiert|"
            r"ist vollständig korrekt|sind vollständig korrekt|"
            r"ist regelkonform|sind regelkonform)\b",

            r"\b(?:keine fehler vorhanden|keine fehler gefunden|"
            r"keine logischen fehler vorhanden|"
            r"keine offensichtlichen fehler vorhanden)\b",
        )

        unsupported = any(
            not is_explicitly_uncertain(sentence)
            and any(
                re.search(pattern, sentence)
                for pattern in affirmative_runtime_patterns
            )
            for sentence in sentences
        )

        if unsupported:
            reasons.append(
                "Die Antwort enthält eine affirmative starke "
                "Funktions-/Korrektheitsaussage, obwohl kein completed "
                "code_test vorliegt."
            )

    if not has_verified_change:
        verification_patterns = (
            r"\b(?:änderung|patch|code)\b.{0,60}\b"
            r"(?:erfolgreich angewendet und verifiziert|"
            r"erfolgreich verifiziert|ist verifiziert|wurde verifiziert)\b",
        )

        unsupported_verification = any(
            not is_explicitly_uncertain(sentence)
            and any(
                re.search(pattern, sentence)
                for pattern in verification_patterns
            )
            for sentence in sentences
        )

        if unsupported_verification:
            reasons.append(
                "Die Antwort behauptet Verifikation ohne verify_change "
                "verified=true."
            )

    return reasons


def agent_v2_final_answer(goal, observations):
    coding_contract = coding_evidence_contract(observations)

    completed_actions = {
        str(item.get("action") or "").strip()
        for item in observations
        if isinstance(item, dict)
        and item.get("status") == "completed"
    }

    has_coding_evidence = bool(
        completed_actions
        & {
            "code_files",
            "code_search",
            "code_read",
            "code_patch",
            "code_diff",
            "code_test",
            "verify_change",
        }
    )

    has_code_test = "code_test" in completed_actions

    has_verified_change = any(
        isinstance(item, dict)
        and item.get("status") == "completed"
        and item.get("action") == "verify_change"
        and isinstance(item.get("result"), dict)
        and item.get("result", {}).get("verified") is True
        for item in observations
    )

    coding_grounding_rules = ""

    if has_coding_evidence:
        coding_grounding_rules = """
WICHTIGE CODING-EVIDENCE-REGELN:

- Die Abschlussantwort MUSS zwischen statischer Codeanalyse,
  ausgeführten Tests und verifizierten Änderungen unterscheiden.
"""

        if not has_code_test:
            coding_grounding_rules += """
- Es wurde KEIN code_test erfolgreich ausgeführt.
- Behandle alle Aussagen zum Code deshalb ausschließlich als statische Analyse.
- Behaupte NICHT als Tatsache, dass der Code funktioniert, funktionsfähig,
  fehlerfrei, korrekt implementiert, regelkonform, vollständig korrekt oder
  erfolgreich ausführbar ist.
- Formulierungen wie "keine Fehler vorhanden", "keine Fehler gefunden",
  "funktioniert korrekt", "technisch funktionsfähig" oder vergleichbare
  Aussagen sind ohne ausgeführte Tests NICHT zulässig.
- Zulässig sind Formulierungen wie:
  "Im statisch gelesenen Code ist kein offensichtlicher Fehler erkennbar"
  oder
  "Die gelesene Implementierung entspricht strukturell dieser Logik;
   das Laufzeitverhalten wurde nicht getestet."
"""

        if not has_verified_change:
            coding_grounding_rules += """
- Es liegt KEIN verify_change mit verified=true vor.
- Behaupte daher NICHT, dass eine Änderung erfolgreich angewendet oder
  verifiziert wurde.
"""

    answer = observed_agent_llm(
        "agent.final",
        [
            {
                "role": "system",
                "content": (
                    "Formuliere ausschließlich anhand der vorhandenen "
                    "Observations eine technische Abschlussantwort. "
                    "Erfinde keine neuen Fakten. "
                    "Trenne klar zwischen beobachteten Fakten aus "
                    "Tool-Ergebnissen, daraus abgeleiteten technischen "
                    "Schlussfolgerungen und Empfehlungen oder Bewertungen. "
                    "Behaupte niemals, eine Webquelle empfehle oder belege "
                    "etwas, wenn dies nicht tatsächlich aus den vorhandenen "
                    "Web-Observations hervorgeht. "
                    "Kennzeichne eigene technische Bewertungen ausdrücklich "
                    "als Bewertung oder Schlussfolgerung. "
                    "Behaupte niemals, eine Datei, Webseite oder Datenquelle "
                    "untersucht zu haben, wenn keine entsprechende "
                    "Observation vorhanden ist. "

                    "WICHTIGE WEB-GROUNDING-REGELN: "
                    "Wenn mindestens eine Web-Observation "
                    "search_degraded=true enthält, erwähne ausdrücklich, "
                    "dass die Webrecherche teilweise degradiert war und "
                    "nicht alle Suchanbieter verfügbar waren. "
                    "Unterscheide strikt zwischen Suchtreffern und tatsächlich "
                    "mit fetch_url geladenen Quellen. "
                    "Eine URL, die nur in web_search-Ergebnissen auftaucht, "
                    "gilt nicht als vollständig untersuchte Quelle. "
                    "Wenn keine offizielle oder primäre Quelle tatsächlich "
                    "mit fetch_url geladen wurde, darfst du nicht behaupten, "
                    "dass etwas offiziell empfohlen, von Apple bestätigt, "
                    "vollständig konform mit Best Practices oder exakt durch "
                    "offizielle Dokumentation belegt sei. "
                    "Formuliere in diesem Fall vorsichtiger, zum Beispiel als "
                    "technische Einschätzung, plausiblen Architekturvergleich "
                    "oder durch Drittquellen gestützte Bewertung. "
                    "Die Begriffe 'vollständig konform', 'offiziell empfohlen', "
                    "'von Apple bestätigt' und 'Best Practice' dürfen nur dann "
                    "als Tatsachen verwendet werden, wenn eine entsprechende "
                    "geladene Primärquelle dies tatsächlich stützt. "
                    "Fehlgeschlagene oder abgelehnte Tool-Aufrufe dürfen "
                    "nicht als erfolgreiche Recherche oder Analyse gezählt "
                    "werden. "
                    "Zähle nur tatsächlich ausgeführte completed-Tool-Aufrufe "
                    "als erfolgreich. "
                    "WICHTIGE SUBAGENT-GROUNDING-REGEL: "
                    "Eine Quelle, die innerhalb eines abgeschlossenen "
                    "Subagent-Ergebnisses deterministisch als loaded=true "
                    "ausgewiesen ist, bleibt gültige Evidence. "
                    "Ein späterer fehlgeschlagener oder abgelehnter "
                    "Parent-Tool-Aufruf auf dieselbe oder eine verwandte URL "
                    "darf diese bereits erfolgreich geladene Child-Evidence "
                    "nicht rückwirkend entwerten. "
                    "Unterscheide deshalb strikt zwischen Child-Observations "
                    "und späteren Parent-Tool-Aufrufen. "

                    "QUALITÄTSREGELN FÜR TECHNISCHE VERGLEICHE: "
                    "Ein Drittanbieter-Repository darf niemals allein als "
                    "offizielle Referenzimplementierung, allgemeiner Standard "
                    "oder aktuelle Best Practice bezeichnet werden. "
                    "Die Existenz unterschiedlicher Ports, Konfigurationen oder "
                    "Implementierungen in verschiedenen Projekten ist für sich "
                    "allein kein Fehler und kein hohes Risiko. "
                    "Bewerte eine lokale Konfiguration nur dann als Problem, "
                    "wenn die Observations einen konkreten Konflikt, eine "
                    "Fehlkonfiguration oder eine Inkompatibilität zeigen. "
                    "Wenn ein lokaler Client einen bestimmten Port erwartet, "
                    "ist dies zunächst nur eine Konfigurationsannahme. "
                    "Ein anderer Default-Port eines Drittprojekts beweist "
                    "keinen Konflikt. "

                    "KONFIGURATIONS- UND DEFAULT-REGEL: "
                    "Ein Unterschied zwischen einem lokal konfigurierten Wert "
                    "und einem dokumentierten Default-Wert einer externen "
                    "Software ist allein kein Fehler, Konflikt oder Hinweis "
                    "auf eine Fehlkonfiguration. "
                    "Dies gilt insbesondere für Ports, Hosts, Pfade, Timeouts "
                    "und andere konfigurierbare Parameter. "
                    "Aus unterschiedlichen Werten darf nicht geschlossen "
                    "werden, dass Systeme inkompatibel sind oder eine "
                    "Verbindung fehlschlägt. "
                    "Eine solche Schlussfolgerung ist nur zulässig, wenn "
                    "Observations die tatsächlich aktive Runtime-Konfiguration "
                    "der beteiligten Komponenten bestätigen. "
                    "Ein dokumentierter Default beschreibt nicht automatisch "
                    "die tatsächlich laufende Konfiguration. "
                    "Wenn nur der lokale Client-Wert und ein externer Default "
                    "bekannt sind, formuliere neutral, dass eine "
                    "Konfigurationsabweichung vorliegt, deren tatsächliche "
                    "Runtime-Kompatibilität nicht verifiziert wurde. "

                    "Verwende starke Bewertungen wie 'hohes Risiko', "
                    "'kritisch', 'falsch', 'nicht konform' oder "
                    "'Best Practice' nur bei konkreter Evidence. "
                    "Wenn die Evidence dafür nicht ausreicht, formuliere "
                    "neutral als mögliche Abhängigkeit, Konfigurationspunkt "
                    "oder technische Einschätzung. "
                    + coding_grounding_rules
                ),
            },
            {
                "role": "user",
                "content": (
                    "ZIEL:\n"
                    + goal
                    + "\n\nOBSERVATIONS:\n"
                    + json.dumps(
                        compact_agent_observations(observations),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n\nDETERMINISTIC CODING EVIDENCE CONTRACT:\n"
                    + json.dumps(
                        coding_contract,
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
            },
        ],
        max_tokens=2400,
        temperature=0.05,
    )

    repair_reasons = coding_final_answer_requires_repair(
        answer,
        observations,
    )

    if repair_reasons:
        answer = observed_agent_llm(
            "agent.final_repair",
            [
                {
                    "role": "system",
                    "content": (
                        "Überarbeite die vorhandene technische Abschlussantwort. "
                        "Erhalte alle durch Observations belegten Fakten und sinnvollen "
                        "Empfehlungen, aber entferne oder schwäche jede unbelegte starke "
                        "Aussage über Funktionsfähigkeit, Korrektheit, Fehlerfreiheit, "
                        "erfolgreiche Ausführung oder Verifikation. "
                        "Wenn kein code_test vorliegt, formuliere ausschließlich als "
                        "statische Codeanalyse und sage ausdrücklich, dass das "
                        "Laufzeitverhalten nicht getestet wurde. "
                        "Erfinde keine neuen Fakten."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "REPAIR-GRÜNDE:\n"
                        + json.dumps(
                            repair_reasons,
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n\nEVIDENCE CONTRACT:\n"
                        + json.dumps(
                            coding_contract,
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n\nZU ÜBERARBEITENDE ANTWORT:\n"
                        + answer
                    ),
                },
            ],
            max_tokens=2400,
            temperature=0.0,
        )

    return answer




def boost_orchestrator_research_query(goal, query):
    """
    Steer technical orchestrator searches toward primary sources without
    changing regular web searches globally.
    """
    goal_value = str(goal or "").lower()
    value = str(query or "").strip()

    if not value:
        return value

    technical_markers = (
        "best practice",
        "best-practice",
        "best practices",
        "dokumentation",
        "documentation",
        "framework",
        "library",
        "bibliothek",
        "repository",
        "repo",
        "github",
        "api",
        "server",
        "installation",
        "konfiguration",
        "configuration",
        "version",
        "release",
        "inference",
        "inferenz",
    )

    is_technical = any(
        marker in goal_value or marker in value.lower()
        for marker in technical_markers
    )

    if not is_technical:
        return value

    # Do not expand the request twice.
    lower = value.lower()

    if (
        "official documentation" in lower
        or "official docs" in lower
        or "official github" in lower
    ):
        return value

    return (
        value
        + " official documentation official GitHub repository"
    )


def sanitize_orchestrator_web_query(goal, query):
    """
    Remove stale model-invented years from web queries for explicitly
    current research.
    """
    from datetime import datetime

    value = str(query or "").strip()
    goal_value = str(goal or "").lower()

    if not value:
        return value

    freshness_markers = (
        "aktuell",
        "aktuelle",
        "aktuellen",
        "neueste",
        "neuesten",
        "latest",
        "current",
        "heute",
        "best practice",
        "best-practice",
        "best practices",
    )

    if not any(marker in goal_value for marker in freshness_markers):
        return value

    current_year = datetime.now().year

    def replace_year(match):
        year = int(match.group(0))

        if year == current_year:
            return match.group(0)

        if 2000 <= year < current_year:
            return ""

        return match.group(0)

    value = re.sub(r"\b20\d{2}\b", replace_year, value)
    value = re.sub(r"\s+", " ", value).strip()

    return value


def source_is_primary_for_goal(goal, reference):
    """
    Conservatively determine whether a loaded web source qualifies as a
    primary source for the specific research goal.

    GitHub and raw GitHub project sources are accepted only when the goal
    explicitly names both the owner and repository.

    An arbitrary github.com result is not automatically a primary source.
    """
    from urllib.parse import urlsplit

    goal_value = str(goal or "").strip().lower()
    reference = str(reference or "").strip()

    if not goal_value or not reference:
        return False

    try:
        parsed = urlsplit(reference)
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False

    host = (parsed.hostname or "").lower()
    parts = [
        part
        for part in parsed.path.split("/")
        if part
    ]

    # --------------------------------------------------------
    # github.com/<owner>/<repo>/...
    # --------------------------------------------------------
    if host == "github.com":
        if len(parts) < 2:
            return False

        owner = parts[0].lower()
        repo = parts[1].lower()

    # --------------------------------------------------------
    # raw.githubusercontent.com/<owner>/<repo>/<branch>/...
    # --------------------------------------------------------
    elif host == "raw.githubusercontent.com":
        if len(parts) < 2:
            return False

        owner = parts[0].lower()
        repo = parts[1].lower()

    else:
        return False

    # GitHub allows .git at the end of a repository name.
    if repo.endswith(".git"):
        repo = repo[:-4]

    def normalize_identifier(value):
        return "".join(
            char
            for char in str(value or "").lower()
            if char.isalnum()
        )

    normalized_goal = normalize_identifier(goal_value)
    normalized_owner = normalize_identifier(owner)
    normalized_repo = normalize_identifier(repo)

    # Deliberately strict:
    # both the owner and repository must be identifiable in the goal.
    if not normalized_owner or not normalized_repo:
        return False

    return (
        normalized_owner in normalized_goal
        and normalized_repo in normalized_goal
    )


def deterministic_loaded_web_sources(goal, sub_result):
    """
    Extract only successfully loaded web sources from child observations and
    assign primary-source status deterministically.
    """
    sources = []

    if not isinstance(sub_result, dict):
        return sources

    seen = set()

    for observation in sub_result.get("steps") or []:
        if not isinstance(observation, dict):
            continue

        if observation.get("action") != "fetch_url":
            continue

        if observation.get("status") != "completed":
            continue

        result = observation.get("result")

        if not isinstance(result, dict):
            continue

        if result.get("ok") is not True:
            continue

        reference = str(
            result.get("url")
            or result.get("requested_url")
            or ""
        ).strip()

        if not reference:
            continue

        if reference in seen:
            continue

        seen.add(reference)

        sources.append({
            "type": "web",
            "reference": reference[:2000],
            "loaded": True,
            "primary": source_is_primary_for_goal(
                goal,
                reference,
            ),
        })

    return sources


def build_subagent_report(agent_name, goal, sub_result):
    """
    Create a compact, structured agent-to-agent handoff.

    Build the report only from the actual child result and its observations.
    It does not change tool permissions or execute tools itself.
    """
    agent_name = str(agent_name or "").strip()
    goal = str(goal or "").strip()

    if not isinstance(sub_result, dict):
        return {
            "summary": "",
            "findings": [],
            "sources": [],
            "limitations": [
                "Kein gültiges strukturiertes Subagent-Ergebnis vorhanden."
            ],
            "confidence": 0.0,
        }

    child_status = str(
        sub_result.get("status") or ""
    ).strip()

    child_answer = str(
        sub_result.get("answer") or ""
    ).strip()

    child_steps = compact_agent_observations(
        sub_result.get("steps") or []
    )

    verified_web_sources = deterministic_loaded_web_sources(
        goal,
        sub_result,
    )

    system_prompt = """
Du erzeugst einen internen strukturierten Report für einen übergeordneten
Orchestrator.

Du darfst AUSSCHLIESSLICH Informationen aus SUBAGENT_RESULT und
SUBAGENT_OBSERVATIONS verwenden.

Erfinde keine Fakten, Quellen, Dateien, Tool-Ergebnisse oder Sicherheiten.

Antworte ausschließlich mit EINEM JSON-Objekt dieses Schemas:

{
  "summary": "Kurze Zusammenfassung der tatsächlich ermittelten Ergebnisse",
  "findings": [
    {
      "claim": "Konkrete Feststellung",
      "evidence": "Konkrete Observation oder Tool-Evidence"
    }
  ],
  "sources": [
    {
      "type": "web | file | code | system | knowledge",
      "reference": "URL, Dateipfad oder konkrete Datenquelle",
      "loaded": true,
      "primary": false
    }
  ],
  "limitations": [
    "Konkrete Einschränkung der Untersuchung"
  ],
  "confidence": 0.0
}

Regeln:

- confidence liegt zwischen 0.0 und 1.0.
- confidence bewertet ausschließlich die Stärke der vorhandenen Evidence.
- Suchtreffer allein sind keine vollständig geladenen Webquellen.
- Eine Webquelle ist nur loaded=true, wenn sie tatsächlich erfolgreich
  geladen wurde.
- Setze primary IMMER auf false. Die Primary-Einstufung wird nachträglich
  ausschließlich deterministisch aus den tatsächlichen Tool-Observations
  berechnet.
- Ein Suchtreffer, eine Drittseite, ein Blog, Forum, Aggregator oder eine
  bloße Behauptung im Antworttext ist niemals ausreichend für Primary-Evidence.
- Fehlgeschlagene oder abgelehnte Tools sind keine Evidence.
- Nicht vollständig gelesene Dateien dürfen nicht als vollständig
  untersucht dargestellt werden.
- Bei fehlender Primärquelle muss dies unter limitations erscheinen,
  sofern das Ziel eine offizielle Aussage oder Primärquelle verlangt.
- findings müssen durch die vorhandenen Observations belegbar sein.
- Verwende keine Markdown-Codeblöcke.
""".strip()

    payload = {
        "agent": agent_name,
        "goal": goal,
        "status": child_status,
        "answer": child_answer,
        "observations": child_steps,
    }

    raw = observed_agent_llm(
        "agent.subagent_report",
        [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ],
        max_tokens=1400,
        temperature=0.0,
    )

    try:
        report = parse_agent_json(raw)
    except Exception:
        report = {}

    if not isinstance(report, dict):
        report = {}

    summary = str(
        report.get("summary") or child_answer[:2000]
    ).strip()

    findings = report.get("findings")
    if not isinstance(findings, list):
        findings = []

    clean_findings = []
    for item in findings[:20]:
        if not isinstance(item, dict):
            continue

        claim = str(
            item.get("claim") or ""
        ).strip()

        evidence = str(
            item.get("evidence") or ""
        ).strip()

        if not claim:
            continue

        clean_findings.append({
            "claim": claim[:1500],
            "evidence": evidence[:2000],
        })

    sources = report.get("sources")
    if not isinstance(sources, list):
        sources = []

    clean_sources = []
    for item in sources[:20]:
        if not isinstance(item, dict):
            continue

        source_type = str(
            item.get("type") or ""
        ).strip().lower()

        reference = str(
            item.get("reference") or ""
        ).strip()

        if source_type not in {
            "web",
            "file",
            "code",
            "system",
            "knowledge",
        }:
            continue

        if not reference:
            continue

                # URLs are web sources even when the report LLM
                # incorrectly labels them as "file".
        if reference.lower().startswith(
            ("http://", "https://")
        ):
            source_type = "web"

        clean_sources.append({
            "type": source_type,
            "reference": reference[:2000],
            "loaded": bool(item.get("loaded")),
        # The LLM must not determine primary-source status.
            "primary": False,
        })

    # --------------------------------------------------------
        # Web sources actually loaded through tool evidence take precedence
        # over the report LLM classification.
    # --------------------------------------------------------

    deterministic_by_reference = {
        str(item.get("reference") or ""): item
        for item in verified_web_sources
        if isinstance(item, dict)
        and str(item.get("reference") or "").strip()
    }

    merged_sources = []
    seen_references = set()

    for item in clean_sources:
        reference = str(
            item.get("reference") or ""
        ).strip()

        if not reference:
            continue

        verified = deterministic_by_reference.get(reference)

        if verified:
            item = {
                **item,
                "type": "web",
                "loaded": True,
                "primary": bool(
                    verified.get("primary")
                ),
            }

        merged_sources.append(item)
        seen_references.add(reference)

    for reference, verified in deterministic_by_reference.items():
        if reference in seen_references:
            continue

        merged_sources.append(verified)

    clean_sources = merged_sources

    limitations = report.get("limitations")
    if not isinstance(limitations, list):
        limitations = []

    clean_limitations = [
        str(item).strip()[:1500]
        for item in limitations[:20]
        if str(item).strip()
    ]

    try:
        confidence = float(
            report.get("confidence", 0.0)
        )
    except Exception:
        confidence = 0.0

    confidence = max(
        0.0,
        min(1.0, confidence),
    )

    return {
        "summary": summary[:3000],
        "findings": clean_findings,
        "sources": clean_sources,
        "limitations": clean_limitations,
        "confidence": confidence,
    }


def research_goal_requires_primary_source(goal):
    """
    Determine whether the research goal explicitly requires an official or
    primary source.
    """
    value = str(goal or "").strip().lower()

    markers = (
        "primärquelle",
        "primaerquelle",
        "primary source",
        "primary-source",
        "offizielle quelle",
        "offizieller quelle",
        "offiziellen quelle",
        "offizielle dokumentation",
        "offizieller dokumentation",
        "offiziellen dokumentation",
        "official source",
        "official documentation",
        "offizielle primärquelle",
        "offizielle primaerquelle",
    )

    return any(marker in value for marker in markers)


def assess_subagent_report(agent_name, goal, report):
    """
    Evaluate the quality of a structured subagent report deterministically
    without an additional LLM call.

    This function does not execute tools or change permissions.
    """
    agent_name = str(agent_name or "").strip().lower()
    goal = str(goal or "").strip().lower()

    if not isinstance(report, dict):
        return {
            "evidence_sufficient": False,
            "needs_verification": True,
            "confidence": 0.0,
            "findings_count": 0,
            "loaded_sources_count": 0,
            "reason": "Kein gültiger strukturierter Report vorhanden.",
        }

    try:
        confidence = float(
            report.get("confidence", 0.0)
        )
    except Exception:
        confidence = 0.0

    confidence = max(
        0.0,
        min(1.0, confidence),
    )

    findings = report.get("findings")
    if not isinstance(findings, list):
        findings = []

    sources = report.get("sources")
    if not isinstance(sources, list):
        sources = []

    limitations = report.get("limitations")
    if not isinstance(limitations, list):
        limitations = []

    valid_findings = [
        item
        for item in findings
        if isinstance(item, dict)
        and str(item.get("claim") or "").strip()
        and str(item.get("evidence") or "").strip()
    ]

    loaded_sources = [
        item
        for item in sources
        if isinstance(item, dict)
        and bool(item.get("loaded"))
        and str(item.get("reference") or "").strip()
    ]

    loaded_web_sources = [
        item
        for item in loaded_sources
        if str(item.get("type") or "").strip().lower() == "web"
    ]

    loaded_code_sources = [
        item
        for item in loaded_sources
        if str(item.get("type") or "").strip().lower()
        in {"code", "file"}
    ]

    loaded_primary_web_sources = [
        item
        for item in loaded_web_sources
        if bool(item.get("primary"))
    ]

    primary_source_required = (
        agent_name == "research"
        and research_goal_requires_primary_source(goal)
    )

    reasons = []
    warnings = []

    # LLM confidence is only the report's self-assessment.
    # Deterministically confirmed tool evidence takes precedence.
    deterministic_evidence_present = bool(loaded_sources)

    if confidence < 0.65:
        if deterministic_evidence_present:
            warnings.append(
                f"Niedrige Report-Confidence ({confidence:.2f}), "
                "aber deterministisch geladene Evidence ist vorhanden."
            )
        else:
            reasons.append(
                f"Niedrige Evidence-Confidence ({confidence:.2f})."
            )

    if not valid_findings:
        reasons.append(
            "Keine belastbaren Findings mit Evidence vorhanden."
        )

    if agent_name == "coding_analysis":
        if not loaded_code_sources:
            reasons.append(
                "Keine tatsächlich geladene Code-/Dateiquelle vorhanden."
            )

    if agent_name == "research":
        if not loaded_web_sources:
            reasons.append(
                "Keine tatsächlich geladene Webquelle vorhanden."
            )

        if (
            primary_source_required
            and not loaded_primary_web_sources
        ):
            reasons.append(
                "Das Research-Ziel verlangt ausdrücklich eine offizielle "
                "Quelle oder Primärquelle, aber keine tatsächlich geladene "
                "Webquelle ist als Primärquelle belegt."
            )

    evidence_sufficient = not reasons
    needs_verification = not evidence_sufficient

    return {
        "evidence_sufficient": evidence_sufficient,
        "needs_verification": needs_verification,
        "confidence": confidence,
        "findings_count": len(valid_findings),
        "loaded_sources_count": len(loaded_sources),
        "loaded_web_sources_count": len(loaded_web_sources),
        "loaded_primary_web_sources_count": len(
            loaded_primary_web_sources
        ),
        "primary_source_required": primary_source_required,
        "loaded_code_sources_count": len(loaded_code_sources),
        "limitations_count": len([
            item
            for item in limitations
            if str(item).strip()
        ]),
        "warnings": warnings,
        "reason": (
            " ".join(reasons)
            if reasons
            else (
                "Subagent-Report besitzt ausreichende strukturierte Evidence."
                + (
                    " " + " ".join(warnings)
                    if warnings
                    else ""
                )
            )
        ),
    }



def canonical_github_repo_from_goal(goal):
    """
    Conservatively extract an explicitly named GitHub owner/repo from the goal.

    Supported forms:
      - https://github.com/owner/repo
      - github.com/owner/repo
      - owner/repo

    Do not infer an unspecified repository.
    """
    value = str(goal or "").strip()

    if not value:
        return None

    patterns = (
        r'https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)',
        r'github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)',
        r'(?<![\w.-])([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?![\w.-])',
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            value,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        owner = match.group(1).strip()
        repo = match.group(2).strip().rstrip(".,;:)")

        if not owner or not repo:
            continue

        blocked_owners = {
            "http",
            "https",
            "api",
            "v1",
            "v2",
            "docs",
        }

        if owner.lower() in blocked_owners:
            continue

        return {
            "owner": owner,
            "repo": repo,
            "url": f"https://github.com/{owner}/{repo}",
        }

    return None


def degraded_empty_web_search_count(observations):
    """
    Count executed web searches that were degraded and returned no results.
    """
    count = 0

    for item in observations or []:
        if not isinstance(item, dict):
            continue

        if item.get("status") != "completed":
            continue

        if item.get("action") not in {
            "web_search",
            "search_web",
        }:
            continue

        result = item.get("result")

        if not isinstance(result, dict):
            continue

        if (
            result.get("search_degraded") is True
            and not result.get("results")
        ):
            count += 1

    return count


def run_agent_v2(
    goal,
    observations=None,
    start_step=1,
    mode="diagnostic",
    conversation_context=None,
    progress_callback=None,
    allow_approval=True,
):
    goal = str(goal or "").strip()
    mode = str(mode or "diagnostic").strip().lower()

    max_steps = {
        "research": 6,
        "diagnostic": 6,
        "coding": 24,
        "orchestrator": 12,
    }.get(mode, 6)

    # Research keeps its regular six-step budget.
    # At most three additional planner steps are available for
    # controlled continuation of already loaded, truncated web sources.
    research_continuation_steps = 3 if mode == "research" else 0
    loop_max_steps = max_steps + research_continuation_steps

    if not goal:
        raise HTTPException(
            status_code=400,
            detail="Kein Agent-Ziel angegeben",
        )

    observations = list(observations or [])

    def publish(status="running", current_step=None, pending_action=None):
        if progress_callback:
            try:
                progress_callback(
                    status,
                    observations,
                    current_step,
                    pending_action,
                )
            except Exception:
                pass

    if mode == "coding" and ambiguous_delete_reference(
        goal,
        conversation_context,
    ):
        result={
            "status": "completed",
            "goal": goal,
            "steps": observations,
            "answer": (
                "Welche konkrete Datei, Seite oder welches Modul soll "
                "gelöscht werden? Ohne eindeutige Referenz bereite ich "
                "keinen DELETE-Patch vor."
            ),
        }
        publish("completed")
        return result

    for step in range(
        start_step,
        loop_max_steps + 1,
    ):
        # Additional research steps are allowed only to continue an
        # already loaded, truncated web source.
        if mode == "research" and step > max_steps:
            continuation_available = any(
                isinstance(item, dict)
                and item.get("status") == "completed"
                and item.get("action") == "fetch_url"
                and isinstance(item.get("result"), dict)
                and item.get("result", {}).get("ok") is True
                and item.get("result", {}).get("truncated") is True
                and item.get("result", {}).get("next_offset") is not None
                for item in observations
            )

            if not continuation_available:
                break
        publish("running", {
            "step": step,
            "action": "agent_plan",
            "reason": "Nächsten sicheren Schritt planen",
            "status": "running",
        })
        decision = agent_choose_next_step_v2(
            goal,
            observations,
            max_steps=max_steps,
            mode=mode,
            conversation_context=conversation_context,
        )

        action = str(
            decision.get("action", "")
        ).strip()
        plan = decision.get("plan")
        if isinstance(plan, list):
            plan = [
                str(item).strip()[:500]
                for item in plan[:12]
                if str(item).strip()
            ]
        else:
            plan = None

        if action == "final":

            # For explicit cross-capability goals, the orchestrator may finish
            # only after the required data sources have been used successfully.
            if mode == "orchestrator":
                missing = orchestrator_missing_evidence(
                    goal,
                    observations,
                )

                if missing:
                    observations.append({
                        "step": step,
                        "action": "evidence_gate",
                        "status": "rejected",
                        "reason": (
                            "Abschluss noch nicht erlaubt; "
                            "erforderliche Evidence fehlt: "
                            + ", ".join(missing)
                        ),
                    })

                    publish("running", observations[-1])
                    continue

                unresolved_quality = (
                    orchestrator_unresolved_subagent_quality(
                        observations
                    )
                )

                if unresolved_quality:
                    still_open = []
                    exhausted = []

                    for item in unresolved_quality:
                        agent_name = str(
                            item.get("agent") or ""
                        ).strip().lower()

                        attempts = orchestrator_delegate_attempts(
                            observations,
                            agent_name,
                        )

                        enriched = dict(item)
                        enriched["attempts"] = attempts

                        verification_exhausted = attempts >= 3

                        if agent_name == "research":
                            research_circuit_broken = any(
                                isinstance(observation, dict)
                                and observation.get("action")
                                == "web_search_circuit_breaker"
                                and observation.get("status") == "rejected"
                                for observation in observations
                            )

                            if research_circuit_broken:
                                verification_exhausted = True
                                enriched["verification_exhausted_by"] = (
                                    "web_search_circuit_breaker"
                                )

                        if verification_exhausted:
                            exhausted.append(enriched)
                        else:
                            still_open.append(enriched)

                    if still_open:
                        details = "; ".join(
                            (
                                str(item.get("agent") or "subagent")
                                + ": "
                                + str(
                                    item.get("reason")
                                    or "Verifikation erforderlich"
                                )
                            )
                            for item in still_open
                        )

                        observations.append({
                            "step": step,
                            "action": "quality_gate",
                            "status": "rejected",
                            "reason": (
                                "Abschluss noch nicht erlaubt; "
                                "Subagent-Evidence benötigt Verifikation: "
                                + details
                            ),
                            "unresolved": still_open,
                        })

                        publish("running", observations[-1])
                        continue

                    if exhausted:
                        details = "; ".join(
                            (
                                str(item.get("agent") or "subagent")
                                + ": "
                                + str(item.get("attempts") or 0)
                                + " Verifikationsversuche; "
                                + str(
                                    item.get("reason")
                                    or "Evidence blieb unzureichend"
                                )
                            )
                            for item in exhausted
                        )

                        observations.append({
                            "step": step,
                            "action": "verification_exhausted",
                            "status": "completed",
                            "reason": (
                                "Weitere gleichartige Verifikationsversuche "
                                "sind voraussichtlich nicht sinnvoll. "
                                "Abschluss ist mit ausdrücklicher "
                                "Kennzeichnung der Unsicherheit erlaubt: "
                                + details
                            ),
                            "agents": exhausted,
                        })

                        publish("running", observations[-1])

                # The orchestrator always synthesizes the final answer again
                # using only the observations.
                final_answer = agent_v2_final_answer(
                    goal,
                    observations,
                )

            elif mode in {"coding", "research"}:
                final_answer = agent_v2_final_answer(
                    goal,
                    observations,
                )

            else:
                final_answer = str(
                    decision.get("answer", "")
                ).strip()

                if not final_answer:
                    final_answer = agent_v2_final_answer(
                        goal,
                        observations,
                    )

            result={
                "status": "completed",
                "goal": goal,
                "steps": observations,
                "answer": final_answer,
            }

            publish("completed")
            return result

        if action == "request_approval":
            if not allow_approval:
                observations.append({
                    "step": step,
                    "action": "approval_guard",
                    "status": "rejected",
                    "reason": (
                        "Delegierte Spezialagenten dürfen keine "
                        "Approval-Aktionen anfordern. "
                        "Arbeite ausschließlich READ-ONLY weiter "
                        "oder schließe mit den vorhandenen "
                        "Beobachtungen ab."
                    ),
                })
                publish("running", observations[-1])
                continue

            operation = str(
                decision.get("operation", "")
            ).strip()

            target = str(
                decision.get("target", "")
            ).strip()

            reason = str(
                decision.get("reason", "")
            ).strip()

            try:
                approval = create_agent_approval(
                    goal=goal,
                    observations=observations,
                    step=step,
                    mode=mode,
                    operation=operation,
                    target=target,
                    reason=reason,
                    conversation_context=conversation_context,
                )

            except Exception as exc:
                observations.append({
                    "step": step,
                    "action": "request_approval",
                    "status": "failed",
                    "error": str(exc),
                })
                publish()
                continue

            result={
                "status": "approval_required",
                "goal": goal,
                "steps": observations,
                "pending_action": approval,
            }
            publish("approval_required", pending_action=approval)
            return result

        # -------------------------------------------------
        # Orchestrator v2: kontrollierte Subagent-Delegation
        # -------------------------------------------------
        if action == "delegate_agent":
            if mode != "orchestrator":
                observations.append({
                    "step": step,
                    "action": "delegate_agent",
                    "status": "rejected",
                    "reason": (
                        "Nur der Orchestrator darf Teilaufgaben "
                        "an Spezialagenten delegieren."
                    ),
                })
                publish("running", observations[-1])
                continue

            delegate_name = str(
                decision.get("agent", "")
            ).strip().lower()

            delegate_goal = str(
                decision.get("goal", "")
            ).strip()

            delegate_reason = str(
                decision.get("reason", "")
            ).strip()

            delegate_modes = {
                "research": "research",
                "diagnostic": "diagnostic",

                # Deliberately do not start coding_analysis in coding mode.
                # This gives the subagent access only to read tools.
                "coding_analysis": "orchestrator_readonly_code",
            }

            if delegate_name not in delegate_modes:
                observations.append({
                    "step": step,
                    "action": "delegate_agent",
                    "status": "rejected",
                    "reason": (
                        "Unbekannter Spezialagent. Erlaubt sind: "
                        "research, diagnostic, coding_analysis."
                    ),
                    "agent": delegate_name or None,
                })
                publish("running", observations[-1])
                continue

            if not delegate_goal:
                observations.append({
                    "step": step,
                    "action": "delegate_agent",
                    "status": "rejected",
                    "reason": (
                        "delegate_agent benötigt ein konkretes Teilziel."
                    ),
                    "agent": delegate_name,
                })
                publish("running", observations[-1])
                continue

            # -------------------------------------------------
            # Orchestrator v2: Repeat-/Budget-Guard
            # -------------------------------------------------

            delegate_attempts = orchestrator_delegate_attempts(
                observations,
                delegate_name,
            )

            if delegate_attempts >= 3:
                observations.append({
                    "step": step,
                    "action": "delegate_guard",
                    "status": "rejected",
                    "agent": delegate_name,
                    "goal": delegate_goal,
                    "reason": (
                        "Maximale Anzahl sinnvoller Delegationen an "
                        f"{delegate_name} erreicht. "
                        "Wähle eine alternative Strategie oder schließe "
                        "mit den vorhandenen Einschränkungen ab."
                    ),
                })

                publish("running", observations[-1])
                continue

            if orchestrator_duplicate_delegation(
                observations,
                delegate_name,
                delegate_goal,
            ):
                observations.append({
                    "step": step,
                    "action": "delegate_guard",
                    "status": "rejected",
                    "agent": delegate_name,
                    "goal": delegate_goal,
                    "reason": (
                        "Diese Delegation wurde bereits mit praktisch "
                        "demselben Teilziel ausgeführt. "
                        "Formuliere eine andere Verifikationsstrategie "
                        "oder verwende einen anderen Spezialagenten."
                    ),
                })

                publish("running", observations[-1])
                continue

            # Guard against excessively large or abusive delegation goals.
            delegate_goal = delegate_goal[:4000]

            # coding_analysis receives a dedicated read-only assignment.
            # It uses research mode internally, whose tool permissions are
            # also read-only.
            if delegate_name == "coding_analysis":
                delegate_mode = "research"
                effective_goal = (
                    "Analysiere ausschließlich den aktiven lokalen "
                    "Code-Workspace. Verwende code_files, code_search und "
                    "code_read. Verwende keine Webrecherche, sofern sie für "
                    "dieses Teilziel nicht ausdrücklich erforderlich ist. "
                    "Verändere keine Dateien und bereite keine Änderungen "
                    "oder Patches vor.\n\nTeilziel:\n"
                    + delegate_goal
                )
            else:
                delegate_mode = delegate_modes[delegate_name]
                if delegate_name == "research":
                    parent_constraints = str(goal or "").strip()[:4000]
                    effective_goal = (
                        delegate_goal
                        + "\n\nÜbergeordnete Anforderungen des Nutzers, "
                        "die bei diesem Teilziel erhalten bleiben müssen:\n"
                        + parent_constraints
                    )
                else:
                    effective_goal = delegate_goal

            publish("running", {
                "step": step,
                "action": "delegate_agent",
                "status": "running",
                "agent": delegate_name,
                "goal": delegate_goal,
                "reason": delegate_reason,
            })

            try:
                sub_result = run_agent_v2(
                    effective_goal,
                    observations=None,
                    start_step=1,
                    mode=delegate_mode,
                    conversation_context=conversation_context,

                    # No progress_callback:
                    # return subagent steps to the orchestrator as a compact
                    # result first.
                    allow_approval=False,
                    progress_callback=None,
                )

                sub_report = build_subagent_report(
                    delegate_name,
                    effective_goal,
                    sub_result,
                )

                sub_quality = assess_subagent_report(
                    delegate_name,
                    effective_goal,
                    sub_report,
                )

                observations.append({
                    "step": step,
                    "action": "delegate_agent",
                    "status": "completed",
                    "agent": delegate_name,
                    "goal": delegate_goal,
                    "reason": delegate_reason,
                    "result": {
                        "status": sub_result.get("status"),
                        "answer": sub_result.get("answer"),
                        "steps": compact_agent_observations(
                            sub_result.get("steps") or []
                        ),
                        "report": sub_report,
                        "quality": sub_quality,
                    },
                })

            except Exception as exc:
                observations.append({
                    "step": step,
                    "action": "delegate_agent",
                    "status": "failed",
                    "agent": delegate_name,
                    "goal": delegate_goal,
                    "reason": delegate_reason,
                    "error": str(exc),
                })

            publish("running", observations[-1])
            continue

        if not action:
            observations.append({
                "step": step,
                "action": "planner_invalid_action",
                "status": "rejected",
                "reason": (
                    "Planner hat keine gültige action geliefert. "
                    "Wähle ein verfügbares Tool oder final."
                ),
            })
            publish("running", observations[-1])
            continue

        if action not in allowed_agent_tools(mode):
            observations.append({
                "step": step,
                "action": action,
                "status": "rejected",
                "reason": (
                    "Tool ist nicht freigegeben"
                ),
            })
            publish()
            continue

        reason = str(
            decision.get("reason", "")
        ).strip()

        query = str(
            decision.get("query", "")
        ).strip()

        instruction = str(
            decision.get("instruction", "")
        ).strip()

        files = decision.get("files")

        tool_options = decision.get("options")
        if not isinstance(tool_options, dict):
            tool_options = {}

        # -------------------------------------------------
        # Research search-loop guard
        # -------------------------------------------------
        # Research should not consume its entire step budget on new search
        # variations when concrete results already exist. After three web
        # searches, block another search. The planner must then verify existing
        # results with fetch_url or finish with a transparent limitation.
        if (
            mode == "research"
            and action in {"web_search", "search_web"}
        ):
            completed_searches = [
                item
                for item in observations
                if isinstance(item, dict)
                and item.get("status") == "completed"
                and item.get("action") in {"web_search", "search_web"}
            ]

            successful_fetches = [
                item
                for item in observations
                if isinstance(item, dict)
                and item.get("status") == "completed"
                and item.get("action") == "fetch_url"
                and isinstance(item.get("result"), dict)
                and item.get("result", {}).get("ok") is True
            ]

            if len(completed_searches) >= 3 and not successful_fetches:
                candidate_urls = []

                for search_item in reversed(completed_searches):
                    search_result = search_item.get("result")
                    if not isinstance(search_result, dict):
                        continue

                    for result_item in search_result.get("results") or []:
                        if not isinstance(result_item, dict):
                            continue

                        url = str(result_item.get("url") or "").strip()
                        if (
                            url
                            and re.match(
                                r"^https?://",
                                url,
                                flags=re.IGNORECASE,
                            )
                            and url not in candidate_urls
                        ):
                            candidate_urls.append(url)

                        if len(candidate_urls) >= 5:
                            break

                    if len(candidate_urls) >= 5:
                        break

                observations.append({
                    "step": step,
                    "action": "research_search_loop_guard",
                    "status": "rejected",
                    "reason": (
                        "Bereits drei Websuchen ohne erfolgreich geladene "
                        "Quelle ausgeführt. Führe keine weitere Suchvariation "
                        "aus. Lade stattdessen einen vorhandenen Treffer mit "
                        "fetch_url oder schließe transparent ab, falls keine "
                        "brauchbare Quelle vorhanden ist."
                    ),
                    "candidate_urls": candidate_urls,
                })

                publish(
                    "running",
                    observations[-1],
                )

                continue

        # -------------------------------------------------
        # Orchestrator query hardening
        # -------------------------------------------------
        if (
            mode == "orchestrator"
            and action in {"web_search", "search_web"}
            and degraded_empty_web_search_count(observations) >= 3
        ):
            observations.append({
                "step": step,
                "action": "web_search_circuit_breaker",
                "status": "rejected",
                "reason": (
                    "Drei degradierte Websuchen ohne Treffer wurden bereits "
                    "ausgeführt. Weitere identische Websuchen sind aktuell "
                    "nicht sinnvoll. Nutze eine deterministisch ableitbare "
                    "Primärquelle, einen anderen READ-only Belegpfad oder "
                    "schließe mit transparenter Einschränkung ab."
                ),
            })

            publish(
                "running",
                observations[-1],
            )
            continue

        if mode == "orchestrator":

            if action in {"web_search", "search_web"}:
                original_query = query

                query = sanitize_orchestrator_web_query(
                    goal,
                    query,
                )

                sanitized_query = query

                query = boost_orchestrator_research_query(
                    goal,
                    query,
                )

                if original_query != sanitized_query:
                    observations.append({
                        "step": step,
                        "action": "query_sanitizer",
                        "status": "completed",
                        "reason": (
                            "Veraltete Jahreszahlen aus einer "
                            "Aktualitäts-Websuche entfernt"
                        ),
                        "original_query": original_query,
                        "query": sanitized_query,
                    })

                if sanitized_query != query:
                    observations.append({
                        "step": step,
                        "action": "primary_source_booster",
                        "status": "completed",
                        "reason": (
                            "Technische Recherche auf offizielle "
                            "Dokumentation und Repository-Quellen fokussiert"
                        ),
                        "original_query": sanitized_query,
                        "query": query,
                    })

            if action == "fetch_url":

                if not re.match(
                    r"^https?://",
                    query or "",
                    flags=re.IGNORECASE,
                ):
                    observations.append({
                        "step": step,
                        "action": "fetch_url_guard",
                        "status": "rejected",
                        "reason": (
                            "fetch_url benötigt eine konkrete HTTP(S)-URL. "
                            "Eine Suchphrase ist keine URL. Nutze zuerst "
                            "web_search/search_web und danach eine URL "
                            "aus den Suchergebnissen."
                        ),
                        "blocked_query": query or None,
                    })

                    publish(
                        "running",
                        observations[-1],
                    )

                    continue

        # -------------------------------------------------
        # Research / Orchestrator Fetch-URL-Allowlist
        # -------------------------------------------------
        if mode in {"orchestrator", "research"} and action == "fetch_url":

            def normalize_fetch_url(value):
                value = str(value or "").strip()

                if not value:
                    return ""

                try:
                    parts = urlsplit(value)
                except Exception:
                    return value.rstrip("/")

                # The fragment does not affect source identity.
                return urlunsplit((
                    parts.scheme.lower(),
                    parts.netloc.lower(),
                    parts.path.rstrip("/") or "/",
                    parts.query,
                    "",
                ))

            allowed_urls = set()

            for item in observations:
                if not isinstance(item, dict):
                    continue

                if item.get("status") != "completed":
                    continue

                if item.get("action") not in {
                    "web_search",
                    "search_web",
                }:
                    continue

                search_result = item.get("result")

                if not isinstance(search_result, dict):
                    continue

                results = search_result.get("results")

                if not isinstance(results, list):
                    continue

                for search_item in results:
                    if not isinstance(search_item, dict):
                        continue

                    result_url = search_item.get("url")

                    if result_url:
                        allowed_urls.add(
                            normalize_fetch_url(result_url)
                        )

            canonical_repo = canonical_github_repo_from_goal(goal)

            if canonical_repo:
                canonical_url = normalize_fetch_url(
                    canonical_repo.get("url")
                )

                if canonical_url:
                    allowed_urls.add(canonical_url)

            requested_url = normalize_fetch_url(query)

            def fetch_url_is_allowed(requested, allowed):
                """
                Allow exact discovered URLs and genuine subpaths.
                The host and scheme must remain identical.
                """
                if requested == allowed:
                    return True

                try:
                    requested_parts = urlsplit(requested)
                    allowed_parts = urlsplit(allowed)
                except Exception:
                    return False

                if (
                    requested_parts.scheme.lower()
                    != allowed_parts.scheme.lower()
                ):
                    return False

                if (
                    requested_parts.netloc.lower()
                    != allowed_parts.netloc.lower()
                ):
                    return False

                requested_path = (
                    requested_parts.path.rstrip("/") or "/"
                )
                allowed_path = (
                    allowed_parts.path.rstrip("/") or "/"
                )

                # A domain-root match does not automatically
                # allow the entire domain.
                if allowed_path == "/":
                    return False

                return requested_path.startswith(
                    allowed_path + "/"
                )

            matching_allowed_url = next(
                (
                    allowed_url
                    for allowed_url in allowed_urls
                    if fetch_url_is_allowed(
                        requested_url,
                        allowed_url,
                    )
                ),
                None,
            )

            if matching_allowed_url is None:
                observations.append({
                    "step": step,
                    "action": "fetch_url_allowlist_guard",
                    "status": "rejected",
                    "reason": (
                        "fetch_url darf in Research/Orchestrator nur eine zuvor "
                        "gefundene URL oder einen echten Unterpfad dieser "
                        "Quelle öffnen. Andere Hosts oder benachbarte "
                        "Repository-/Pfadbereiche bleiben gesperrt."
                    ),
                    "blocked_query": query or None,
                    "allowed_url_count": len(allowed_urls),
                })
                publish(
                    "running",
                    observations[-1],
                )
                continue

            successful_fetches = sum(
                1
                for item in observations
                if isinstance(item, dict)
                and item.get("status") == "completed"
                and item.get("action") == "fetch_url"
            )

            if successful_fetches >= 3:
                observations.append({
                    "step": step,
                    "action": "fetch_url_limit_guard",
                    "status": "rejected",
                    "reason": (
                        "Bereits drei Web-Quellen erfolgreich geladen. "
                        "Nutze die vorhandenen Quellen zur Synthese oder "
                        "führe nur bei fehlender Evidence eine neue Suche aus."
                    ),
                    "blocked_query": query or None,
                })

                publish(
                    "running",
                    observations[-1],
                )

                continue

        # -------------------------------------------------
        # Deterministic code_search -> code_read targeting
        # -------------------------------------------------
        # If the model requests only the bare file path after a successful
        # code_search, use an exact result from the latest matching search
        # as the line anchor.
        #
        # This turns:
        #   code_search -> agent/app.py:6325
        #   code_read   -> agent/app.py
        #
        # into a targeted read around the match instead of starting at line 1
        # and then paginating sequentially.
        if action == "code_read" and query:
            requested_query = str(query).strip()

            if not re.search(r":\d+(?:-\d+)?$", requested_query):
                anchored_line = None

                for item in reversed(observations):
                    if not isinstance(item, dict):
                        continue
                    if item.get("status") != "completed":
                        continue
                    if item.get("action") != "code_search":
                        continue

                    result = item.get("result")
                    if not isinstance(result, dict):
                        continue

                    results = result.get("results")
                    if not isinstance(results, list):
                        continue

                    matching_hits = [
                        hit
                        for hit in results
                        if isinstance(hit, dict)
                        and str(hit.get("path") or "").strip() == requested_query
                        and str(hit.get("match") or "").strip()
                        in {"exact", "symbol"}
                    ]

                    definition_hits = [
                        hit
                        for hit in matching_hits
                        if re.match(
                            r"^(?:async\s+)?(?:def|class)\s+",
                            str(hit.get("snippet") or "").strip(),
                        )
                    ]

                    candidate_hits = definition_hits or matching_hits

                    for hit in candidate_hits:
                        try:
                            line = int(hit.get("line"))
                        except (TypeError, ValueError):
                            continue

                        if line > 0:
                            anchored_line = line
                            break

                    if anchored_line is not None:
                        break

                if anchored_line is not None:
                    anchor_start = max(1, anchored_line - 60)
                    anchor_end = anchored_line + 120
                    query = (
                        f"{requested_query}:"
                        f"{anchor_start}-{anchor_end}"
                    )

                    observations.append({
                        "step": step,
                        "action": "code_read_search_anchor",
                        "status": "completed",
                        "reason": (
                            "Nackter code_read wurde automatisch auf einen "
                            "exakten Treffer aus der vorherigen code_search "
                            "zentriert."
                        ),
                        "original_query": requested_query,
                        "anchor_line": anchored_line,
                        "query": query,
                    })

                    publish(
                        "running",
                        observations[-1],
                    )

        # -------------------------------------------------
        # Deterministic code_read pagination
        # -------------------------------------------------
        # Local models sometimes omit a new line range when continuing and
        # request the same bare file path again.
        #
        # If that exact path was already read successfully, continue after
        # the most recently read range automatically. This keeps progressive
        # reading reliable even when the model ignores the prompt rule.
        if action == "code_read" and query:
            requested_query = str(query).strip()

            if not re.search(r":\d+(?:-\d+)?$", requested_query):
                previous_reads = [
                    item
                    for item in observations
                    if isinstance(item, dict)
                    and item.get("status") == "completed"
                    and item.get("action") == "code_read"
                    and isinstance(item.get("result"), dict)
                    and str(
                        item.get("result", {}).get("path") or ""
                    ).strip() == requested_query
                ]

                if previous_reads:
                    last_read = previous_reads[-1]
                    last_result = last_read.get("result") or {}

                    try:
                        last_end = int(last_result.get("end_line"))
                    except (TypeError, ValueError):
                        last_end = 0

                    if last_end > 0:
                        next_start = last_end + 1
                        next_end = next_start + 240
                        query = (
                            f"{requested_query}:"
                            f"{next_start}-{next_end}"
                        )

                        observations.append({
                            "step": step,
                            "action": "code_read_pagination",
                            "status": "completed",
                            "reason": (
                                "Identischer code_read ohne Zeilenbereich "
                                "wurde automatisch auf den nächsten "
                                "Dateibereich fortgesetzt."
                            ),
                            "original_query": requested_query,
                            "query": query,
                        })

                        publish(
                            "running",
                            observations[-1],
                        )

        # -------------------------------------------------
        # Repeat and loop guard for agent tool calls
        # -------------------------------------------------
        if mode == "orchestrator":

            completed_tool_calls = [
                item
                for item in observations
                if isinstance(item, dict)
                and item.get("status") == "completed"
            ]

        # 1. Do not repeat an identical action and query.
        # Deliberately exclude instruction from the signature because query
        # is the actual target reference for read tools.
            same_call_count = sum(
                1
                for item in completed_tool_calls
                if str(item.get("action") or "").strip() == action
                and str(item.get("query") or "").strip() == query
                and (
                    action != "disk_usage"
                    or item.get("options") == (tool_options or None)
                )
                and (
                    action not in {"web_search", "search_web"}
                    or (
                        isinstance(item.get("result"), dict)
                        and bool(
                            item.get("result", {}).get("results")
                        )
                    )
                )
            )

            if same_call_count >= 1:
                observations.append({
                    "step": step,
                    "action": "repeat_guard",
                    "status": "rejected",
                    "reason": (
                        "Identischer Tool-Aufruf wurde bereits erfolgreich "
                        f"ausgeführt: {action} / {query or '<ohne query>'}. "
                        "Nutze einen anderen Suchbegriff, einen anderen "
                        "Zeilenbereich, fetch_url oder schließe die Analyse ab."
                    ),
                    "blocked_action": action,
                    "blocked_query": query or None,
                })
                publish("running", observations[-1])
                continue

        # 2. Limit web searches.
        # After three successful searches, inspect results more deeply or
        # synthesize them instead of consuming more similar search runs.
            if action in {"web_search", "search_web"}:
                web_search_count = sum(
                    1
                    for item in completed_tool_calls
                    if item.get("action") in {
                        "web_search",
                        "search_web",
                    }
                    and isinstance(item.get("result"), dict)
                    and bool(
                        item.get("result", {}).get("results")
                    )
                )

                if web_search_count >= 3:
                    observations.append({
                        "step": step,
                        "action": "web_search_guard",
                        "status": "rejected",
                        "reason": (
                            "Bereits drei Web-Suchen erfolgreich ausgeführt. "
                            "Nutze jetzt fetch_url für relevante Treffer "
                            "oder synthetisiere die vorhandenen Ergebnisse."
                        ),
                        "blocked_action": action,
                        "blocked_query": query or None,
                    })
                    publish("running", observations[-1])
                    continue

        publish("running", {
            "step": step,
            "action": action,
            "reason": reason,
            "plan": plan,
            "query": query or None,
            "options": tool_options or None,
            "status": "running",
        })

        try:
            result = execute_read_only_agent_tool(
                action,
                goal,
                query=query or None,
                instruction=instruction or None,
                files=files,
                options=tool_options,
            )

            observations.append({
                "step": step,
                "action": action,
                "reason": reason,
                "plan": plan,
                "query": query or None,
                "options": tool_options or None,
                "instruction": instruction or None,
                "status": "completed",
                "result": result,
            })
            publish()

        except Exception as exc:
            observations.append({
                "step": step,
                "action": action,
                "reason": reason,
                "plan": plan,
                "query": query or None,
                "options": tool_options or None,
                "status": "failed",
                "error": str(exc),
            })
            publish()

    final_status = "max_steps"

    if mode == "orchestrator":
        missing = orchestrator_missing_evidence(
            goal,
            observations,
        )

        if not missing:
            # All evidence types required for the goal are available.
            # At the step limit, the agent may therefore synthesize and
            # finish cleanly.
            final_status = "completed"

        else:
            observations.append({
                "step": max_steps,
                "action": "evidence_gate",
                "status": "rejected",
                "reason": (
                    "Schrittbudget erreicht; "
                    "erforderliche Evidence fehlt: "
                    + ", ".join(missing)
                ),
            })

    result = {
        "status": final_status,
        "goal": goal,
        "steps": observations,
        "answer": agent_v2_final_answer(
            goal,
            observations,
        ),
    }

    publish(final_status)

    return result



def verify_agent_action(pending):
    """
    Perform mandatory technical verification after an approved
    state-changing action.
    """
    operation = pending["operation"]
    target = pending["target"]

    if operation == "code_apply":
        patch_id = validate_agent_patch_id(target)

        try:
            patch_diff = code_workspaces.diff(patch_id)
            tests = code_workspaces.test(patch_id)
            files = code_workspaces.verify(patch_id)

            patch_status = patch_diff.get("status")
            tests_ok = tests.get("passed") is True
            files_ok = files.get("verified") is True

            verified = (
                patch_status == "applied"
                and tests_ok
                and files_ok
            )

            return {
                "verified": verified,
                "checks": [
                    {
                        "check": "patch_status",
                        "ok": patch_status == "applied",
                        "status": patch_status,
                    },
                    {
                        "check": "code_test",
                        "ok": tests_ok,
                        "result": tests,
                    },
                    {
                        "check": "workspace_files",
                        "ok": files_ok,
                        "result": files,
                    },
                ],
                "patch_id": patch_id,
            }

        except Exception as exc:
            return {
                "verified": False,
                "checks": [],
                "patch_id": patch_id,
                "error": str(exc),
            }

    if operation != "docker_restart":
        return {
            "verified": False,
            "checks": [],
            "error": (
                "Für diese Aktion existiert noch keine "
                "Verifikationsroutine"
            ),
        }

    checks = []

    # Allow a short startup delay after a restart.
    _agent_time.sleep(2)

    # -----------------------------------------------------
    # Docker-State / Health
    # -----------------------------------------------------

    try:
        inspect_result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{json .State}}",
                target,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            stdin=subprocess.DEVNULL,
        )

        state_raw = (
            inspect_result.stdout or ""
        ).strip()

        state = {}

        if (
            inspect_result.returncode == 0
            and state_raw
        ):
            try:
                state = json.loads(state_raw)
            except Exception:
                state = {}

        running = bool(
            state.get("Running", False)
        )

        health = (
            state.get("Health", {}) or {}
        ).get("Status")

        docker_ok = (
            inspect_result.returncode == 0
            and running
            and health not in {
                "unhealthy",
            }
        )

        checks.append({
            "check": "docker_state",
            "ok": docker_ok,
            "running": running,
            "health": health,
            "exit_code": state.get("ExitCode"),
            "error": (
                inspect_result.stderr or ""
            ).strip(),
        })

    except Exception as exc:
        docker_ok = False

        checks.append({
            "check": "docker_state",
            "ok": False,
            "error": str(exc),
        })

    # -----------------------------------------------------
    # Determine published ports
    # -----------------------------------------------------

    published_ports = []

    try:
        port_result = subprocess.run(
            [
                "docker",
                "port",
                target,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
        )

        if port_result.returncode == 0:
            for line in (
                port_result.stdout or ""
            ).splitlines():

                if "->" not in line:
                    continue

                _, host_part = line.split(
                    "->",
                    1,
                )

                host_part = host_part.strip()

                # Beispiele:
                # 0.0.0.0:3000
                # [::]:3000
                match = re.search(
                    r":(\d+)$",
                    host_part,
                )

                if match:
                    port = int(
                        match.group(1)
                    )

                    if port not in published_ports:
                        published_ports.append(
                            port
                        )

    except Exception as exc:
        checks.append({
            "check": "docker_ports",
            "ok": False,
            "error": str(exc),
        })

    # -----------------------------------------------------
    # HTTP-Verifikation
    # -----------------------------------------------------

    http_ok = None

    if published_ports:
        http_ok = False

        # Check only the first published port.
        port = published_ports[0]
        url = f"http://127.0.0.1:{port}/"

        last_error = None
        status_code = None

        # Some applications need a few seconds after a Docker restart
        # before HTTP becomes available.
        for attempt in range(1, 6):
            try:
                request = urllib.request.Request(
                    url,
                    method="GET",
                    headers={
                        "User-Agent": (
                            "MLX-Nobby-Agent/1.0"
                        ),
                    },
                )

                with urllib.request.urlopen(
                    request,
                    timeout=8,
                ) as response:
                    status_code = (
                        response.status
                    )

                if 200 <= status_code < 500:
                    http_ok = True
                    break

            except urllib.error.HTTPError as exc:
                status_code = exc.code

                if 200 <= exc.code < 500:
                    http_ok = True
                    break

                last_error = str(exc)

            except Exception as exc:
                last_error = str(exc)

            if attempt < 5:
                _agent_time.sleep(2)

        checks.append({
            "check": "http",
            "ok": http_ok,
            "url": url,
            "status_code": status_code,
            "error": last_error,
        })

    else:
        checks.append({
            "check": "http",
            "ok": None,
            "reason": (
                "Container veröffentlicht keinen "
                "ermittelbaren TCP-Port"
            ),
        })

    # Docker must be running.
    #
    # HTTP must succeed when a port is available.
    verified = bool(
        docker_ok
        and (
            http_ok is True
            or http_ok is None
        )
    )

    return {
        "verified": verified,
        "operation": operation,
        "target": target,
        "checks": checks,
    }


@app.post("/api/agent/approve/{approval_id}")
def api_agent_approve(
    approval_id: str,
    request: AgentApprovalRequest,
):
    with PENDING_AGENT_ACTIONS_LOCK:
        pending = PENDING_AGENT_ACTIONS.pop(
            approval_id,
            None,
        )

    if pending is None:
        raise HTTPException(
            status_code=404,
            detail="Freigabe nicht gefunden oder bereits verwendet",
        )

    if _agent_time.time() > pending["expires_at"]:
        raise HTTPException(
            status_code=410,
            detail="Freigabe ist abgelaufen",
        )

    observations = list(
        pending["observations"]
    )

    step = int(
        pending["step"]
    )

    if not request.approved:
        observations.append({
            "step": step,
            "action": pending["operation"],
            "target": pending["target"],
            "status": "rejected_by_user",
        })

        return run_agent_v2(
            pending["goal"],
            observations,
            step + 1,
            mode=pending.get("mode", "diagnostic"),
            conversation_context=pending.get("conversation_context"),
        )

    try:
        result = execute_agent_approved_action(
            pending
        )

        status_value = (
            "completed"
            if result["returncode"] == 0
            else "failed"
        )

        observations.append({
            "step": step,
            "action": pending["operation"],
            "target": pending["target"],
            "status": status_value,
            "result": result,
        })

        # ---------------------------------------------
        # Change -> Verify
        # ---------------------------------------------

        if result["returncode"] == 0:
            verification = verify_agent_action(
                pending
            )

            observations.append({
                "step": step,
                "action": "verify_change",
                "target": pending["target"],
                "status": (
                    "completed"
                    if verification.get(
                        "verified"
                    )
                    else "failed"
                ),
                "result": verification,
            })

    except Exception as exc:
        observations.append({
            "step": step,
            "action": pending["operation"],
            "target": pending["target"],
            "status": "failed",
            "error": str(exc),
        })

    # A successfully applied and verified code patch is a terminal state.
    # No further planner run is needed.
    if pending["operation"] == "code_apply":
        verification_result = next(
            (
                item.get("result", {})
                for item in reversed(observations)
                if item.get("action") == "verify_change"
            ),
            {},
        )

        if verification_result.get("verified") is True:
            return {
                "status": "completed",
                "goal": pending["goal"],
                "steps": observations,
                "pending_action": None,
                "answer": (
                    "Änderung erfolgreich angewendet und verifiziert."
                ),
            }

    return run_agent_v2(
        pending["goal"],
        observations,
        step + 1,
        mode=pending.get("mode", "diagnostic"),
        conversation_context=pending.get("conversation_context"),
    )


# ============================================================
# Uploaded Document RAG API
# ============================================================

class DocumentIndexRequest(BaseModel):
    document_id: str
    name: str
    pages: list[dict]
    document_type: str = "pdf"


class DocumentSearchRequest(BaseModel):
    document_id: str
    query: str
    limit: int = 6


def _set_document_index_job(document_id, **values):
    with DOCUMENT_INDEX_JOBS_LOCK:
        job = DOCUMENT_INDEX_JOBS.setdefault(document_id, {})
        job.update(values)
        job["updated_at"] = time.time()


def _run_document_index_job(request_data):
    document_id = request_data["document_id"]

    try:
        def progress(done, total):
            percent = (
                round((done / total) * 100, 1)
                if total
                else 100.0
            )

            _set_document_index_job(
                document_id,
                status="indexing",
                chunks_done=done,
                chunks_total=total,
                progress=percent,
            )

        result = knowledge.index_uploaded_document(
            document_id=document_id,
            name=request_data["name"],
            pages=request_data["pages"],
            document_type=request_data["document_type"],
            progress_callback=progress,
        )

        _set_document_index_job(
            document_id,
            status="ready",
            chunks_done=result.get("chunks", 0),
            chunks_total=result.get("chunks", 0),
            progress=100.0,
            cached=bool(result.get("cached", False)),
            result=result,
            error=None,
        )

    except Exception as exc:
        _set_document_index_job(
            document_id,
            status="error",
            error=str(exc),
        )


@app.post("/api/documents/index")
def index_uploaded_document_api(request: DocumentIndexRequest):
    document_id = request.document_id

    with DOCUMENT_INDEX_JOBS_LOCK:
        existing = DOCUMENT_INDEX_JOBS.get(document_id)

        if existing and existing.get("status") in {
            "queued",
            "indexing",
        }:
            return {
                "document_id": document_id,
                **existing,
            }

        DOCUMENT_INDEX_JOBS[document_id] = {
            "status": "queued",
            "chunks_done": 0,
            "chunks_total": 0,
            "progress": 0.0,
            "cached": False,
            "error": None,
            "updated_at": time.time(),
        }

    request_data = {
        "document_id": request.document_id,
        "name": request.name,
        "pages": request.pages,
        "document_type": request.document_type,
    }

    worker = threading.Thread(
        target=_run_document_index_job,
        args=(request_data,),
        name=f"document-index-{document_id[:8]}",
        daemon=True,
    )
    worker.start()

    return {
        "document_id": document_id,
        "status": "queued",
        "chunks_done": 0,
        "chunks_total": 0,
        "progress": 0.0,
        "cached": False,
    }


@app.get("/api/documents/status/{document_id}")
def document_index_status(document_id: str):
    with DOCUMENT_INDEX_JOBS_LOCK:
        job = DOCUMENT_INDEX_JOBS.get(document_id)

        if not job:
            return {
                "document_id": document_id,
                "status": "unknown",
                "chunks_done": 0,
                "chunks_total": 0,
                "progress": 0.0,
            }

        return {
            "document_id": document_id,
            **job,
        }


@app.get("/api/documents/{document_id}/page/{page}")
def get_uploaded_document_page_api(
    document_id: str,
    page: int,
):
    try:
        return knowledge.get_uploaded_document_page(
            document_id=document_id,
            page=page,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


@app.post("/api/documents/search")
def search_uploaded_document_api(request: DocumentSearchRequest):
    try:
        return knowledge.search_uploaded_document(
            document_id=request.document_id,
            query=request.query,
            limit=request.limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
