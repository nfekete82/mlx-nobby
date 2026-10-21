"""Explicit launcher-only adapter for Agent's durable media queue."""
from __future__ import annotations

import json


def stored_blockers(path, kind):
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
        raise RuntimeError(f"Unverified {kind} job store")
    terminal = {"completed", "failed", "cancelled", "interrupted", "discarded", "paused"}
    return [{"kind": kind, "id": k, "status": v.get("status", "unknown")}
            for k, v in data.items() if v.get("status") not in terminal]


def install_queue(queue, gate):
    if getattr(queue, "_benchmark_admission_installed", False):
        raise RuntimeError("Queue admission already installed")
    original_load, original_enqueue, original_update = queue._ensure_loaded_locked, queue.enqueue, queue._update
    tickets = {}
    # The legacy loader treats corrupt stores as empty. Admission must not do so.
    stored_blockers(queue.QUEUE_FILE, "media_queue")

    def loaded():
        original_load()
        for job_id in list(tickets):
            if job_id not in queue._jobs or queue._jobs[job_id].get("status") in queue.TERMINAL:
                tickets.pop(job_id).close()
        # Caller holds the existing queue RLock. Restore queued work before readiness.
        for job_id, job in queue._jobs.items():
            if job.get("status") not in queue.TERMINAL and job_id not in tickets:
                tickets[job_id] = gate.ticket()

    def enqueue(*args, **kwargs):
        ticket = gate.ticket()  # Before persistence, scheduler wake or HTTP acceptance.
        try:
            with queue._jobs_lock:
                result = original_enqueue(*args, **kwargs)
                job_id = result["id"]
                if job_id in tickets:
                    ticket.close()  # loaded() already registered this job while enqueuing.
                elif result.get("status") in queue.TERMINAL:
                    ticket.close()
                else:
                    tickets[job_id] = ticket
                return result
        except BaseException:
            ticket.close()
            raise

    def update(job_id, **changes):
        with queue._jobs_lock:
            result = original_update(job_id, **changes)
            if result and result.get("status") in queue.TERMINAL:
                ticket = tickets.pop(job_id, None)
                if ticket:
                    ticket.close()
            return result

    queue._ensure_loaded_locked, queue.enqueue, queue._update = loaded, enqueue, update
    queue._benchmark_admission_installed = True
    # Read existing state and acquire queued-job tickets before the server is ready.
    with queue._jobs_lock:
        loaded()
    def refresh():
        with queue._jobs_lock:
            loaded()
    return refresh
