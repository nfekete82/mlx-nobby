"""Explicit future server launcher; never used to modify an already running server.

Example: python -m ltx_lab.guarded_serve --role video -- -m uvicorn
video_service_dispatch:app --host 127.0.0.1 --port 8060
"""
from __future__ import annotations

import argparse
import contextvars
import functools
import importlib
import os
import runpy
import sys
import threading
from pathlib import Path
from contextlib import contextmanager

from .admission import AdmissionMiddleware, CURRENT, Gate

JOB_MODULES = ("agent.", "backend.openai_gateway", "video_service", "image_service", "speech.")
JOB_NAMES = ("video-job-", "image-job-", "talking-photo-", "mlx-short-", "mlx-chat-stream",
             "file-analysis-", "batch-", "document-index-", "mlx-image-prewarm")


def record_model_paths(utils):
    """Observe the real loader's path resolution, never resolve an ID diagnostically."""
    original = utils.get_model_path
    evidence = {}
    def resolve(path_or_hf_repo, *args, **kwargs):
        path = original(path_or_hf_repo, *args, **kwargs)
        paths = evidence.setdefault(str(path_or_hf_repo), [])
        resolved = str(Path(path).resolve())
        if resolved not in paths:
            paths.append(resolved)  # Multiple revisions remain ambiguous; never overwrite history.
        return path
    utils.get_model_path = resolve
    return evidence, lambda: setattr(utils, "get_model_path", original)


@contextmanager
def track_job_threads(gate=None):
    """Acquire before Thread.start returns: queued work survives request completion.

    Persistent upstream model scheduler threads are intentionally excluded. Their
    actual inference requests are held by the HTTP ticket and upstream metrics.
    """
    original = threading.Thread.start
    @functools.wraps(original)
    def start(thread, *args, **kwargs):
        parent = CURRENT.get()
        target = getattr(thread, "_target", None)
        module = getattr(target, "__module__", "")
        if thread.name in {"mlx-unified-media-queue", "mlx-automation-scheduler"}:
            return original(thread, *args, **kwargs)
        if not (thread.name.startswith(JOB_NAMES + ("mlx-automation-",))
                or (parent and module.startswith(JOB_MODULES))):
            return original(thread, *args, **kwargs)
        ticket = (parent.gate if parent else gate or Gate()).ticket()
        previous = thread.run
        context = contextvars.copy_context()
        def work():
            token = CURRENT.set(ticket)
            try:
                previous()
            finally:
                CURRENT.reset(token)
                ticket.close()
        thread.run = lambda: context.run(work)
        try:
            return original(thread, *args, **kwargs)
        except BaseException:
            ticket.close()
            thread.run = previous
            raise
    threading.Thread.start = start
    try:
        yield
    finally:
        threading.Thread.start = original


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--role", required=True, choices=("chat", "router", "agent", "video", "image", "speech", "musetalk", "embedding"))
    p.add_argument("command", nargs=argparse.REMAINDER)
    args = p.parse_args(argv)
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if len(command) < 2 or command[0] != "-m" or command[1] not in {
        "uvicorn", "mlx_vlm", "model_lifecycle_launcher"
    }:
        p.error("Only -m uvicorn, -m mlx_vlm or the guarded chat lifecycle launcher is supported")
    if command[1] == "model_lifecycle_launcher" and (
        args.role != "chat" or os.environ.get("MLX_LIFECYCLE_ENABLE") != "1"
        or command[2:3] != ["server"]
    ):
        p.error("The lifecycle launcher is supported only for chat with explicit lifecycle opt-in")
    if any(v == "--reload" or v.startswith("--workers") for v in command):
        p.error("Reload/multi-worker launch is unsupported; admission proof must identify the listener PID")
    # Restrict model-owning restore runtimes, not Agent's download/model-management features.
    if args.role in {"chat", "router", "musetalk"}:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    offline = (os.environ.get("HF_HUB_OFFLINE") == "1"
               and os.environ.get("TRANSFORMERS_OFFLINE") == "1")
    import uvicorn
    from uvicorn.importer import import_from_string
    original = uvicorn.run
    cli_module = importlib.import_module("uvicorn.main")
    original_cli_run = cli_module.run
    gate = Gate()
    hub_cache = None
    resolutions, undo_paths = {}, lambda: None
    refresh = None
    if args.role in {"chat", "router", "musetalk"}:
        from huggingface_hub import constants
        if not constants.HF_HUB_OFFLINE:
            raise ValueError("HF was imported before offline mode; refuse ambiguous deployment")
        hub_cache = str(constants.HF_HUB_CACHE)
    if args.role in {"chat", "router"}:
        from mlx_vlm import utils
        resolutions, undo_paths = record_model_paths(utils)
    if args.role == "agent":
        from agent import media_queue
        from .queue_admission import install_queue, stored_blockers
        refresh_queue = install_queue(media_queue, gate)
        def refresh():
            refresh_queue()
            home = Path.home() / ".config/mlx-web"
            blockers = stored_blockers(home / "batch/jobs.json", "batch")
            blockers += stored_blockers(home / "shorts/jobs.json", "shorts")
            for path in (home / "talking-photo/jobs").glob("*.json"):
                import json
                job = json.loads(path.read_text())
                if job.get("status") not in {"completed", "failed", "cancelled", "interrupted", "discarded"}:
                    blockers.append({"kind": "talking_photo", "id": job.get("id"), "status": job.get("status")})
            return {"job_blockers": blockers}
    def guarded(app, **kwargs):
        if kwargs.get("reload") or kwargs.get("workers", 1) not in (None, 1) or kwargs.get("factory"):
            raise ValueError("Unsupported launcher lifecycle")
        if isinstance(app, str):
            app = import_from_string(app)
        return original(AdmissionMiddleware(app, role=args.role, offline=offline, tracking=True,
                                            gate=gate, hub_cache=hub_cache, refresh=refresh,
                                            model_resolutions=resolutions), **kwargs)
    uvicorn.run = guarded
    cli_module.run = guarded
    previous = sys.argv
    sys.argv = command[1:]
    try:
        with track_job_threads(gate):
            runpy.run_module(command[1], run_name="__main__")
    finally:
        uvicorn.run = original
        cli_module.run = original_cli_run
        undo_paths()
        sys.argv = previous


if __name__ == "__main__":
    main()
