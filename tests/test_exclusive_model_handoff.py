"""Exclusive cross-model handoffs preserve the existing memory admission guards.

No model is loaded in these tests. All external service calls are simulated.
"""
import tempfile
import threading
from pathlib import Path
from unittest import mock

import runtime_coordinator as runtime


SAFE = {
    "pressure": "normal",
    "total_gb": 48.0,
    "used_estimate_gb": 12.0,
    "free_percent": 75.0,
    "headroom_gb": 30.0,
    "swap_used_gb": 1.0,
}


def services():
    resident = {"image": True, "speech": True, "musetalk": True}
    observed = []

    def requester(method, url, payload=None, timeout=10):
        kind = next((k for k, root in (
            ("image", runtime.IMAGE_URL),
            ("speech", runtime.SPEECH_URL),
            ("musetalk", runtime.MUSETALK_URL),
            ("video", runtime.VIDEO_URL),
        ) if url.startswith(root)), None)
        if kind is None:
            raise AssertionError((method, url))
        observed.append((method, kind))
        if method == "POST":
            assert kind in resident
            assert url.endswith("/unload")
            resident[kind] = False
            return {"ok": True}
        assert method == "GET" and url.endswith("/health")
        return {
            "ok": True, "status": "ready", "active_generation": False,
            "loaded": resident.get(kind, False),
            "tts_loaded": False, "tts_clone_loaded": False,
        }

    return observed, resident, requester


def test_image_exclusive_releases_chat_speech_and_musetalk_when_headroom_is_safe():
    calls, resident, requester = services()
    chat = []
    with tempfile.TemporaryDirectory() as directory, mock.patch.object(
        runtime, "ensure_model_load_allowed"
    ) as guard:
        with runtime.image_runtime(
            threading.Event(),
            requester=requester,
            chat_loaded=lambda: True,
            chat_command=chat.append,
            memory_snapshot=lambda: SAFE.copy(),
            lock_path=Path(directory) / "runtime.lock",
            exclusive_models=True,
        ) as status:
            assert chat == ["stop"]
            assert status["exclusive_models"] is True
            assert status["speech_released"] is True
            assert status["musetalk_released"] is True
            assert status["chat_released"] is True
            guard.assert_called_once()
    assert chat == ["stop", "start"]
    assert resident["speech"] is False and resident["musetalk"] is False
    assert ("POST", "speech") in calls
    assert ("POST", "musetalk") in calls


def test_video_exclusive_releases_image_speech_musetalk_and_chat():
    calls, resident, requester = services()
    chat = []
    with tempfile.TemporaryDirectory() as directory, mock.patch.object(
        runtime, "memory_budget_snapshot", return_value=SAFE.copy()
    ), mock.patch.object(runtime, "ensure_model_load_allowed") as guard:
        with runtime.video_runtime(
            threading.Event(),
            chat_loaded=lambda: True,
            chat_command=chat.append,
            requester=requester,
            lock_path=Path(directory) / "runtime.lock",
            exclusive_models=True,
        ) as status:
            assert status["exclusive_models"]
            assert status["image_released"]
            assert not status["image_preserved"]
            assert status["speech_released"]
            assert status["musetalk_released"]
            assert status["chat_released"]
            assert chat == ["stop"]
            guard.assert_called_once()
    assert chat == ["stop", "start"]
    assert all(not value for value in resident.values())
    assert [name for method, name in calls if method == "POST"] == [
        "image", "speech", "musetalk"
    ]


def test_chat_exclusive_evicts_idle_media_weights_but_never_stops_chat():
    calls, resident, requester = services()
    with tempfile.TemporaryDirectory() as directory:
        with runtime.chat_runtime(
            threading.Event(),
            requester=requester,
            lock_path=Path(directory) / "runtime.lock",
            exclusive_models=True,
        ):
            assert not any(resident.values())
    assert [name for method, name in calls if method == "POST"] == [
        "image", "speech", "musetalk"
    ]


def test_pressure_policy_preserves_old_nonexclusive_image_behavior():
    calls, resident, requester = services()
    with tempfile.TemporaryDirectory() as directory:
        with runtime.image_runtime(
            threading.Event(),
            requester=requester,
            chat_loaded=lambda: True,
            chat_command=lambda action: (_ for _ in ()).throw(AssertionError(action)),
            memory_snapshot=lambda: SAFE.copy(),
            lock_path=Path(directory) / "runtime.lock",
            exclusive_models=False,
        ) as status:
            assert not status["exclusive_models"]
            assert status["chat_released"] is False
            assert status["speech_released"] is False
            assert status["musetalk_released"] is False
    assert all(resident.values())
    assert all(method != "POST" for method, _ in calls)


def test_exclusive_handoff_fails_closed_if_known_loaded_model_wont_unload():
    calls, resident, requester = services()
    def uncooperative(method, url, payload=None, timeout=10):
        if url.startswith(runtime.SPEECH_URL):
            if method == "POST": return {"ok": True}
            return {"status": "ready", "loaded": True, "tts_loaded": False}
        return requester(method, url, payload, timeout)
    with tempfile.TemporaryDirectory() as directory:
        with mock.patch.object(runtime, "memory_budget_snapshot", return_value=SAFE.copy()):
            try:
                with runtime.chat_runtime(requester=uncooperative,
                                          lock_path=Path(directory) / "runtime.lock",
                                          exclusive_models=True):
                    raise AssertionError("Unsafe concurrent model admission")
            except RuntimeError as exc:
                assert "Speech-Runtime konnte nicht entladen" in str(exc)


def test_image_service_evicts_warm_sdxl_before_starting_qwen_edit(monkeypatch):
    """Same image-service process must not retain SDXL weights under Qwen."""
    import image_service as image
    from contextlib import contextmanager

    job_id = "exclusive-model-handoff-image"
    state = {"sdxl_loaded": True, "events": []}

    @contextmanager
    def exclusive_lease(_cancel_event, **kwargs):
        assert kwargs["exclusive_models"] is True
        state["events"].append("lease")
        yield {"chat_released": True}

    def shutdown():
        state["events"].append("sdxl-unload")
        state["sdxl_loaded"] = False

    def edit(*_args, **_kwargs):
        state["events"].append("qwen-edit")
        assert state["sdxl_loaded"] is False
        return {"id": "1791111111-aaaaaaaaaaaa", "path": "/tmp/edited.png"}

    monkeypatch.setattr(image.runtime_coordinator, "image_runtime", exclusive_lease)
    monkeypatch.setattr(image, "sdxl_worker_running",
                        lambda: state["sdxl_loaded"])
    monkeypatch.setattr(image, "shutdown_sdxl_worker", shutdown)
    monkeypatch.setattr(image, "_edit_result", edit)

    image._jobs[job_id] = {
        "id": job_id, "status": "queued", "phase": "queued",
        "operation": "edit", "_cancel_event": threading.Event(),
        "created_at": 1.0, "total_steps": 20,
    }
    try:
        image._run_image_job(job_id, "edit",
                             image.Edit(prompt="Change the selected eye color",
                                        source_path="/tmp/original.png"),
                             release_lock=False)
        assert image._jobs[job_id]["status"] == "completed"
        assert state["events"] == ["lease", "sdxl-unload", "qwen-edit"]
    finally:
        image._jobs.pop(job_id, None)


def test_image_service_fails_closed_if_warm_sdxl_refuses_to_release(monkeypatch):
    import image_service as image
    from contextlib import contextmanager
    job_id = "exclusive-model-handoff-failure"

    @contextmanager
    def lease(_cancel_event, **_kwargs):
        yield {}

    monkeypatch.setattr(image.runtime_coordinator, "image_runtime", lease)
    monkeypatch.setattr(image, "sdxl_worker_running", lambda: True)
    monkeypatch.setattr(image, "shutdown_sdxl_worker", lambda: None)
    called = []
    monkeypatch.setattr(image, "_edit_result", lambda *_args, **_kwargs: called.append(True))
    image._jobs[job_id] = {
        "id": job_id, "status": "queued", "phase": "queued",
        "operation": "edit", "_cancel_event": threading.Event(),
        "created_at": 1.0, "total_steps": 20,
    }
    try:
        image._run_image_job(job_id, "edit",
                             image.Edit(prompt="Enhance marked eyes",
                                        source_path="/tmp/original.png"),
                             release_lock=False)
        assert image._jobs[job_id]["status"] == "failed"
        assert "SDXL-Worker" in image._jobs[job_id]["error"]
        assert called == []
    finally:
        image._jobs.pop(job_id, None)
