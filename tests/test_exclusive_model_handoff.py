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

def test_exclusive_native_runtime_verifies_4b_release_before_media_admission():
    """Direct native image/video requests cannot bypass the 4B supervisor."""
    from agent import memory_model_coordination as ctl

    seen = []
    def memory_preflight(kind, timeout_seconds=20, *, exclusive=False):
        seen.append((kind, exclusive))
        return True
    with tempfile.TemporaryDirectory() as directory, \
         mock.patch.object(ctl, "prepare_media_dispatch", side_effect=memory_preflight), \
         mock.patch.object(runtime, "memory_budget_snapshot", return_value=SAFE.copy()), \
         mock.patch.object(runtime, "ensure_model_load_allowed"), \
         mock.patch.object(runtime, "release_idle_image_runtime", return_value={"released": False, "loaded": False}), \
         mock.patch.object(runtime, "release_idle_speech_runtime", return_value={"released": False}), \
         mock.patch.object(runtime, "release_idle_musetalk_runtime", return_value={"released": False}), \
         mock.patch.object(runtime, "wait_for_idle", return_value={"status": "ready"}):
        with runtime.image_runtime(
            threading.Event(), lock_path=Path(directory) / "image.lock",
            chat_loaded=lambda: False, exclusive_models=True,
        ):
            pass
        with runtime.video_runtime(
            threading.Event(), lock_path=Path(directory) / "video.lock",
            chat_loaded=lambda: False, chat_command=lambda action: None,
            exclusive_models=True,
        ):
            pass
    assert seen == [("image", True), ("video", True)]


def test_exclusive_native_media_fails_before_model_loading_if_4b_busy():
    from agent import memory_model_coordination as ctl
    with tempfile.TemporaryDirectory() as directory, \
         mock.patch.object(ctl, "prepare_media_dispatch", return_value=False), \
         mock.patch.object(runtime, "ensure_model_load_allowed") as admission:
        try:
            with runtime.image_runtime(
                threading.Event(), lock_path=Path(directory) / "runtime.lock",
                chat_loaded=lambda: False, exclusive_models=True,
            ):
                raise AssertionError("Unsafe model admission")
        except runtime.ServiceUnavailable as exc:
            assert "4B" in str(exc)
    admission.assert_not_called()


def test_direct_image_generate_edit_and_upscale_use_exclusive_runtime(monkeypatch):
    """The older synchronous routes must share the same protective lease."""
    import image_service as image
    from contextlib import contextmanager
    calls = []

    @contextmanager
    def guarded(_cancel_event, **kwargs):
        calls.append(kwargs)
        yield {"suppress_chat_restore": False}

    monkeypatch.setattr(image.runtime_coordinator, "image_runtime", guarded)
    monkeypatch.setattr(image, "_release_unused_image_models", lambda selected=None: None)
    monkeypatch.setattr(image, "sdxl_worker_running", lambda: False)
    monkeypatch.setattr(image, "shutdown_sdxl_worker", lambda: None)
    monkeypatch.setattr(image, "_resolve_generation", lambda request: {
        "model": {"provider": "sdxl", "id": "fixture"}
    })
    monkeypatch.setattr(image, "_generate_result", lambda request, **kw: {"id": "fixture"})
    monkeypatch.setattr(image, "_edit_result", lambda request: {"id": "fixture"})
    monkeypatch.setattr(image, "_upscale_result", lambda request: {"id": "fixture"})

    assert image.generate(image.Generate(prompt="Synthetic terrain"))["id"] == "fixture"
    assert image.edit(image.Edit(prompt="Edit synthetic picture", source_path="/tmp/a.png"))["id"] == "fixture"
    assert image.upscale(image.Upscale(source_path="/tmp/a.png"))["id"] == "fixture"
    assert len(calls) == 3
    assert all(call.get("exclusive_models") is True for call in calls)


def test_image_model_cache_releases_other_models_and_rejects_unknown(monkeypatch):
    import image_service as image
    calls = []
    state = {"sdxl": True}
    monkeypatch.setattr(image, "sdxl_worker_running", lambda: state["sdxl"])
    def shutdown():
        calls.append("sdxl")
        state["sdxl"] = False
    monkeypatch.setattr(image, "shutdown_sdxl_worker", shutdown)
    monkeypatch.setattr(image, "_loaded_mlxserve_repository_ids", lambda: ["model-a", "model-b"])
    monkeypatch.setattr(image.registry, "load_registry", lambda: {
        "models": [
            {"repository": "model-a", "provider": "mlxserve"},
            {"repository": "model-b", "provider": "mlxserve"},
        ]
    })
    monkeypatch.setattr(image, "_unload_mlxserve_model_and_wait",
                        lambda model: calls.append(model["repository"]))
    image._release_unused_image_models({"provider": "mlxserve", "repository": "model-a"})
    assert calls == ["sdxl", "model-b"]

    monkeypatch.setattr(image, "_loaded_mlxserve_repository_ids", lambda: ["unknown-weights"])
    try:
        image._release_unused_image_models({"provider": "sdxl"})
    except RuntimeError as exc:
        assert "unbekanntes MLX-Serve-Modell" in str(exc)
    else:
        raise AssertionError("Unknown weights must not coexist with SDXL")

def test_mlxserve_release_error_suppresses_chat_restore_for_direct_edit(monkeypatch):
    """A failed provider unload must never restart 27B over resident weights."""
    import image_service as image
    from contextlib import contextmanager
    observed = {}

    @contextmanager
    def guarded(_cancel, **kwargs):
        assert kwargs.get("exclusive_models") is True
        yield observed

    def cannot_unload(_request):
        raise image.ImageModelReleaseError("MLX-Serve edit weights still loaded")

    monkeypatch.setattr(image.runtime_coordinator, "image_runtime", guarded)
    monkeypatch.setattr(image, "_release_unused_image_models", lambda selected=None: None)
    monkeypatch.setattr(image, "sdxl_worker_running", lambda: False)
    monkeypatch.setattr(image, "_edit_result", cannot_unload)

    try:
        image.edit(image.Edit(prompt="Synthetic local edit", source_path="/tmp/test.png"))
    except Exception as exc:
        assert "MLX-Serve" in str(exc)
    else:
        raise AssertionError("Edit with failed model unload must not succeed")
    assert observed.get("suppress_chat_restore") is True


def test_mlxserve_release_error_suppresses_chat_restore_for_queued_edit(monkeypatch):
    import image_service as image
    from contextlib import contextmanager

    seen = {}
    job_id = "exclusive-model-release-error-queued"

    @contextmanager
    def guarded(_cancel, **kwargs):
        assert kwargs.get("exclusive_models") is True
        yield seen

    def cannot_unload(*args, **kwargs):
        raise image.ImageModelReleaseError("MLX-Serve edit weights still loaded")

    monkeypatch.setattr(image.runtime_coordinator, "image_runtime", guarded)
    monkeypatch.setattr(image, "_release_unused_image_models", lambda selected=None: None)
    monkeypatch.setattr(image, "sdxl_worker_running", lambda: False)
    monkeypatch.setattr(image, "_edit_result", cannot_unload)
    image._jobs[job_id] = {
        "id": job_id, "status": "queued", "phase": "queued",
        "operation": "edit", "_cancel_event": threading.Event(),
        "created_at": 1.0, "total_steps": 20,
    }
    try:
        image._run_image_job(
            job_id, "edit",
            image.Edit(prompt="Synthetic local edit", source_path="/tmp/test.png"),
            release_lock=False,
        )
        assert image._jobs[job_id]["status"] == "failed"
        assert seen.get("suppress_chat_restore") is True
    finally:
        image._jobs.pop(job_id, None)

def test_unmanaged_mlxserve_image_weights_stay_visible_and_block_video_handoff(monkeypatch):
    """Never report image runtime unloaded while unknown weights remain."""
    import image_service as image
    from fastapi import HTTPException

    model = {"id": "fixture", "provider": "sdxl", "enabled": True}
    monkeypatch.setattr(image.registry, "load_registry",
                        lambda: {"default_model": "fixture", "models": [model]})
    monkeypatch.setattr(image.registry, "get_model", lambda: model)
    monkeypatch.setattr(image, "_loaded_mlxserve_models", lambda: [])
    monkeypatch.setattr(image, "_loaded_mlxserve_repository_ids",
                        lambda: ["unmanaged-image-model"])
    monkeypatch.setattr(image, "sdxl_worker_running", lambda: False)
    monkeypatch.setattr(image, "shutdown_sdxl_worker", lambda: None)
    assert image.health()["loaded"] is True
    assert image.health()["running_model"] == "unmanaged-mlxserve"
    try:
        image.unload()
    except HTTPException as exc:
        assert exc.status_code == 500
        assert "vollständig entladen" in str(exc.detail)
    else:
        raise AssertionError("Unknown image weight must block video handoff")



def test_embedding_weights_do_not_poison_image_health_or_chat_unload(monkeypatch):
    """Regression: embedding-only 4B resident in shared 11234 is NOT an image."""
    import io
    import json
    import image_service as image

    embedding = {
        "id": "mlx-community/Qwen3-Embedding-4B-4bit-DWQ",
        "loaded": True,
        # Some mlx-serve versions omit the capabilities field entirely.
    }
    other = {
        "id": "ddalcu/Qwen-Image-2.1-MLX-Serve-4bit",
        "loaded": False,
        "capabilities": ["image_generation"],
    }

    def fake_urlopen(request, timeout):
        assert str(request).endswith("/v1/models")
        return io.BytesIO(json.dumps({"data": [embedding, other]}).encode())

    model = {"id": "fixture", "provider": "sdxl", "enabled": True}
    monkeypatch.setattr(image.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(image.registry, "load_registry",
                        lambda: {"default_model": "fixture", "models": [model]})
    monkeypatch.setattr(image.registry, "get_model", lambda: model)
    monkeypatch.setattr(image, "_running", None)
    monkeypatch.setattr(image, "_active_job_id", None)
    monkeypatch.setattr(image, "sdxl_worker_running", lambda: False)
    monkeypatch.setattr(image, "shutdown_sdxl_worker", lambda: None)

    assert image._loaded_mlxserve_repository_ids() == []
    assert image.health()["loaded"] is False
    assert image.health()["running_model"] is None
    assert image.unload()["loaded"] is False


def test_embedding_capability_and_unknown_model_safety_remain_separate(monkeypatch):
    import io
    import json
    import image_service as image
    from fastapi import HTTPException

    loaded = [
        {"id": "org/private-vector-model", "capabilities": ["embeddings"], "loaded": True},
        {"id": "unknown-native-model", "loaded": True},
        {"id": "org/image-model", "capabilities": ["text_to_image"], "loaded": False},
    ]

    monkeypatch.setattr(
        image.urllib.request,
        "urlopen",
        lambda request, timeout: io.BytesIO(
            json.dumps({"data": loaded}).encode()
        ),
    )
    assert image._loaded_mlxserve_repository_ids() == ["unknown-native-model"]
    monkeypatch.setattr(image, "shutdown_sdxl_worker", lambda: None)
    monkeypatch.setattr(image, "sdxl_worker_running", lambda: False)
    monkeypatch.setattr(image.registry, "load_registry",
                        lambda: {"models": [], "default_model": None})
    try:
        image.unload()
    except HTTPException as exc:
        assert exc.status_code == 500
    else:
        raise AssertionError("Unknown non-embedding weights must block image handoff")


def test_embedding_capability_dict_is_recognized():
    import image_service as image
    assert image._mlxserve_entry_is_embedding({
        "id": "org/custom", "capabilities": {"embeddings": True}
    })
    assert not image._mlxserve_entry_is_embedding({
        "id": "org/custom", "capabilities": ["image_generation"]
    })
