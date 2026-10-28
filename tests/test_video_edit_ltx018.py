"""CPU-only acceptance and security checks for LTX 0.18 Extend/Retake endpoints."""
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
from unittest import mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent import video_edit_routes as edit


def source(tmp_path):
    root = tmp_path / "videos"
    root.mkdir()
    ident = "a" * 24
    path = root / (ident + ".mp4")
    path.write_bytes(b"\x00\x00\x00\x18ftyp" + b"test" * 100)
    return path, ident


def test_request_schema_rejects_path_traversal_bogus_types_and_bounded_ranges():
    ok = edit.EditRequest(source_kind="video", source_id="a"*24, operation="extend",
                          prompt="Continue the flight", extend_frames=4)
    assert ok.distilled and ok.seed == 42
    for patch in [
        {"source_kind": "../tmp"}, {"source_id": "../etc/passwd"},
        {"source_id": "a" * 23}, {"operation": "delete"}, {"extend_frames": 1000},
        {"prompt": "x"}, {"start_seconds": -1}, {"end_seconds": 61},
        {"operation": "retake", "start_seconds": 2, "end_seconds": 1},
        {"model": "remote/fetch"}, {"output": "/etc/hosts"},
    ]:
        with pytest.raises(ValidationError):
            edit.EditRequest(**{**ok.model_dump(), **patch})


def test_source_path_only_managed_local_outputs(tmp_path):
    path, ident = source(tmp_path)
    with mock.patch.object(edit.media_lifecycle, "_root_for", return_value=path.parent),          mock.patch.object(edit.media_lifecycle, "_expected_path", return_value=path):
        assert edit.source_path("video", ident) == path
        path.unlink()
        path.symlink_to(Path("/etc/hosts"))
        with pytest.raises(HTTPException) as exc:
            edit.source_path("video", ident)
        assert exc.value.status_code == 404


def test_ffprobe_validation_and_latent_command_translation(tmp_path):
    path, ident = source(tmp_path)
    result = mock.Mock(returncode=0, stdout=json.dumps({"streams": [{
        "nb_read_frames": "97", "r_frame_rate": "24/1", "width": 704, "height": 448
    }]}))
    with mock.patch.object(edit.subprocess, "run", return_value=result) as run:
        info = edit.probe(path)
    assert "ffprobe" == run.call_args.args[0][0]
    assert info["latent_frames"] == 12
    assert info["duration_seconds"] == 4
    destination = tmp_path / "new.mp4"
    extend = edit.EditRequest(source_kind="video", source_id=ident, operation="extend",
                              prompt="A desert fortress", extend_frames=4)
    cmd = edit.build_command(extend, path, destination, info)
    assert cmd[1] == "extend"
    assert cmd[cmd.index("--extend-frames") + 1] == "4"
    assert "--distilled" in cmd and "--low-ram" in cmd
    assert cmd[cmd.index("--model") + 1] == str(edit.MODEL)
    retake = edit.EditRequest(source_kind="video", source_id=ident, operation="retake",
                              prompt="A desert fortress", distilled=False,
                              start_seconds=1.0, end_seconds=2.0)
    cmd = edit.build_command(retake, path, destination, info)
    assert cmd[1] == "retake"
    assert cmd[cmd.index("--start") + 1] == "3"
    assert cmd[cmd.index("--end") + 1] == "6"
    assert "--no-regen-audio" in cmd
    assert "--distilled" not in cmd
    with pytest.raises(HTTPException) as exc:
        edit.build_command(retake.model_copy(update={"end_seconds": 55}), path, destination, info)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("frames,size,fps", [(17,704,24),(97,700,24),(96,704,24),(97,704,25),(2001,704,24)])
def test_probe_rejects_incompatible_sources(tmp_path, frames, size, fps):
    path, _ = source(tmp_path)
    result = mock.Mock(stdout=json.dumps({"streams": [{
        "nb_read_frames": str(frames), "r_frame_rate": f"{fps}/1",
        "width": size, "height": 448,
    }]}))
    with mock.patch.object(edit.subprocess, "run", return_value=result):
        with pytest.raises(HTTPException) as exc:
            edit.probe(path)
        assert exc.value.status_code == 422


def test_routes_use_verified_sources_and_job_status_does_not_leak_private_data(tmp_path):
    sourcefile, ident = source(tmp_path)
    fake = {"frames": 97, "fps": 24, "latent_frames": 12, "duration_seconds": 4,
            "width": 704, "height": 448}
    handlers = {}
    class FakeApp:
        def get(self, path, **kwargs):
            def register(fn):
                handlers[("GET", path)] = fn
                return fn
            return register

        def post(self, path, **kwargs):
            def register(fn):
                handlers[("POST", path)] = fn
                return fn
            return register
    edit.install_routes(FakeApp())
    with mock.patch.object(edit, "_runtime_ready", return_value=True), \
         mock.patch.object(edit, "source_path", return_value=sourcefile), \
         mock.patch.object(edit, "probe", return_value=fake), \
         mock.patch.object(edit, "_video_idle"), \
         mock.patch.object(edit, "JOB_DIR", tmp_path / "jobs"), \
         mock.patch.object(edit, "OUTPUT", tmp_path / "out"), \
         mock.patch.object(edit.threading, "Thread") as thread:
        payload = edit.EditRequest(source_kind="video", source_id=ident,
                                   operation="extend", prompt="A desert fortress")
        capabilities = handlers[("GET", "/api/video/edit/status")](
            source_kind="video", source_id=ident)
        assert capabilities["ready"] and capabilities["source"]["latent_frames"] == 12
        job = handlers[("POST", "/api/video/edit/jobs")](payload)
        assert job["status"] == "queued"
        assert not any(k.startswith("_") for k in job)
        assert "prompt" not in job
        thread.return_value.start.assert_called_once_with()
        status = handlers[("GET", "/api/video/edit/jobs/{job_id}")](job["id"])
        assert status["id"] == job["id"]
        handlers[("POST", "/api/video/edit/jobs/{job_id}/cancel")](job["id"])
        assert edit._jobs[job["id"]]["_cancel_event"].is_set()
        with pytest.raises(HTTPException) as exc:
            handlers[("GET", "/api/video/edit/jobs/{job_id}")]("../etc/passwd")
        assert exc.value.status_code == 422
    # No real worker started; release the slot and clear mock job state.
    if edit._generation_lock.locked():
        edit._generation_lock.release()
    edit._jobs.clear()


def test_staged_talking_photo_script_uses_dry_run_backup_and_recovery():
    script = Path("scripts/switch-ltx-talking-photo-runtime").read_text()
    compile(script, "scripts/switch-ltx-talking-photo-runtime", "exec")
    for expected in (
        '"ltx-2-mlx-v0.18.0"', '"de.nobby.mlx-agent"', '"--apply"',
        "shutil.copy2(plist, backup)", 'launchctl("bootout", plist)',
        'launchctl("bootstrap", plist)', "ensure_idle()",
        "if JOBS.exists():", '"LTX_MLX_RUNTIME_ROOT"', "verify_checkout(target, args.to)",
        '"ltx-distilled", "ltx-max"',
    ):
        assert expected in script


def test_video_edit_ui_has_two_real_actions_and_generated_video_link():
    source = Path("frontend/assets/chat/media-library.js").read_text()
    editor = Path("frontend/assets/chat/video-edit.js").read_text()
    web = Path("backend/app.py").read_text()
    agent = Path("agent/app.py").read_text()
    assert 'window.MLXVideoEdit?.open?.(asset, "extend")' in source
    assert 'window.MLXVideoEdit?.open?.(asset, "retake")' in source
    assert '"extend", t(' in editor and '"retake", t(' in editor
    assert "/api/mlx/video/edit/jobs" in editor
    assert "job.result.video_url" in editor
    assert "window.MLXVideoEdit = Object.freeze({open})" in editor
    assert "/api/video/edit/jobs" in web
    assert "install_video_edit_routes(app)" in agent
