"""Image visibility during safe SDXL-to-chat handoff.

Tests mock provider and coordinator. No model or GPU required.
"""
from contextlib import contextmanager
from pathlib import Path
import threading

from PIL import Image
import pytest

import image_service as service
from agent import app as agent


IMAGE_ID = "1234567890-aaaaaaaaaaaa"
JOB_ID = "a" * 24


@pytest.mark.parametrize("fail_restore", [False, True])
def test_generated_sdxl_image_is_previewable_only_after_worker_unload(
    monkeypatch, tmp_path, fail_restore,
):
    image_directory = tmp_path / "images"
    image_directory.mkdir()
    path = image_directory / f"{IMAGE_ID}.png"
    monkeypatch.setattr(agent, "IMAGE_DIRECTORY", image_directory)

    marker = []
    with service._jobs_lock:
        service._jobs[JOB_ID] = {
            "id": JOB_ID, "operation": "generate", "status": "queued",
            "_cancel_event": threading.Event(), "_process": None,
        }
        service._active_job_id = JOB_ID

    def fake_generate(
        request, *, provider_options=None, prepared_callback=None,
        saving_callback=None, **_kwargs
    ):
        prepared_callback(
            {"id": "juggernaut-xl", "provider": "sdxl",
             "model_family": "sdxl"},
            {"steps": 40}, path,
        )
        Image.new("RGB", (32, 32), "navy").save(path)
        saving_callback()
        return {
            "id": IMAGE_ID, "path": str(path), "prompt": "Test photo",
            "model": "juggernaut-xl", "provider": "sdxl",
            "width": 32, "height": 32, "steps": 40,
        }

    @contextmanager
    def guarded_runtime(*_args, **_kwargs):
        yield {}
        # This check occurs before image_runtime exits, while the media
        # resource lease is still held and chat is being restored.
        with service._jobs_lock:
            job = dict(service._jobs[JOB_ID])
        assert marker == ["worker_unloaded"]
        assert job["status"] == "saving"
        assert job["phase"] == "restoring_chat"
        preview = agent._image_job_tool_result(job)
        assert preview["status"] == "saving"
        assert preview["artifacts"][0]["image_id"] == IMAGE_ID
        assert path.is_file()
        if fail_restore:
            raise RuntimeError("chat model restart failed")

    monkeypatch.setattr(service, "_generate_result", fake_generate)
    monkeypatch.setattr(service.runtime_coordinator, "image_runtime", guarded_runtime)
    monkeypatch.setattr(
        service, "shutdown_sdxl_worker",
        lambda: marker.append("worker_unloaded"),
    )

    try:
        service._run_image_job(
            JOB_ID, "generate", service.Generate(prompt="Test photo"),
            resolved={"model": {"provider": "sdxl"}}, release_lock=False,
        )
        with service._jobs_lock:
            job = dict(service._jobs[JOB_ID])
        if fail_restore:
            assert job["status"] == "failed"
            assert job["result"] is None
            assert not path.exists()
            assert agent._image_job_tool_result(job)["artifacts"] == []
        else:
            assert job["status"] == "completed"
            assert job["result"]["id"] == IMAGE_ID
            assert path.exists()
            assert len(agent._image_job_tool_result(job)["artifacts"]) == 1
        assert marker == ["worker_unloaded"]
    finally:
        with service._jobs_lock:
            service._jobs.pop(JOB_ID, None)
            service._active_job_id = None


def test_early_artifact_requires_exact_sdxl_restoring_phase(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "IMAGE_DIRECTORY", tmp_path)
    path = tmp_path / f"{IMAGE_ID}.png"
    Image.new("RGB", (8, 8)).save(path)
    base = {
        "id": JOB_ID, "operation": "generate",
        "status": "saving", "phase": "restoring_chat",
        "result": {"id": IMAGE_ID, "path": str(path)},
    }
    assert len(agent._image_job_tool_result(base)["artifacts"]) == 1
    for case in (
        {**base, "phase": "saving"},
        {**base, "status": "running"},
        {**base, "result": None},
        {**base, "operation": "edit"},
    ):
        assert agent._image_job_tool_result(case)["artifacts"] == []
