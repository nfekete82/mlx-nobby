"""Masked Qwen jobs receive the same exclusive chat handoff as SDXL.

No actual model is run. Existing stop/start and watchdog behavior is tested
separately in test_sdxl_memory_safety.py.
"""
import threading
from contextlib import contextmanager

import image_service as service


def _exercise(monkeypatch, *, region: bool):
    observed = []
    job_id = "region-chat-handoff-" + ("yes" if region else "no")

    @contextmanager
    def guarded_image_runtime(cancel_event, *, force_chat_unload=False,
                              exclusive_models=False):
        observed.append((force_chat_unload, exclusive_models))
        yield {"chat_released": force_chat_unload or exclusive_models}

    request = service.Edit(
        prompt="Change only the selected eyes",
        source_path="/managed/images/original.png",
        **({"mask_path": "/managed/images/mask.png", "region_edit": True}
           if region else {}),
    )
    monkeypatch.setattr(service.runtime_coordinator, "image_runtime", guarded_image_runtime)
    monkeypatch.setattr(service, "_edit_result", lambda *_args, **_kwargs: {
        "id": "1791111111-aaaaaaaaaaaa",
        "path": "/managed/images/1791111111-aaaaaaaaaaaa.png",
        "steps": 20,
    })
    service._jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "phase": "queued",
        "operation": "edit",
        "_cancel_event": threading.Event(),
        "created_at": 1.0,
        "current_step": None,
        "total_steps": 20,
        "result": None,
        "error": None,
    }
    try:
        service._run_image_job(job_id, "edit", request, release_lock=False)
        assert service._jobs[job_id]["status"] == "completed"
        assert service._jobs[job_id]["result"]["id"] == "1791111111-aaaaaaaaaaaa"
    finally:
        service._jobs.pop(job_id, None)
    return observed


def test_region_qwen_job_forces_chat_unload_even_without_measured_pressure(monkeypatch):
    assert _exercise(monkeypatch, region=True) == [(True, True)]


def test_ordinary_edit_retains_pressure_based_chat_handoff(monkeypatch):
    assert _exercise(monkeypatch, region=False) == [(False, True)]
