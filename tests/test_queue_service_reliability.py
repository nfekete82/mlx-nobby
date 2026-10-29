import threading
import importlib.util
from unittest import mock

import pytest

from agent import media_queue as queue
import runtime_coordinator as runtime


@pytest.mark.parametrize("code", [409,503])
def test_service_failure_reason_retry_count_and_wait_persist(tmp_path,monkeypatch,code):
    # Other Agent regression tests intentionally keep the real queue scheduler
    # alive. This test needs its own module state so that scheduler cannot add
    # a third dispatch between our two explicit calls.
    spec = importlib.util.spec_from_file_location("isolated_media_queue", queue.__file__)
    isolated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated)
    _assert_retry_state(isolated, tmp_path, monkeypatch, code)


def _assert_retry_state(queue, tmp_path, monkeypatch, code):
    monkeypatch.setattr(queue,"QUEUE_DIRECTORY",tmp_path)
    monkeypatch.setattr(queue,"QUEUE_FILE",tmp_path/"jobs.json")
    monkeypatch.setattr(queue,"_jobs",{})
    monkeypatch.setattr(queue,"_loaded",True)
    monkeypatch.setattr(queue,"ensure_worker",lambda: None)
    job=queue.enqueue("video",{"operation":"t2v","chat_id":"test","payload":{"prompt":"A flight","quality":"quality","duration":20}})
    assert job["automatic_continuation"] and job["stage_count"]==5
    with mock.patch.object(queue,"_service_request",side_effect=queue.ServiceError(code,"Video-Service auf Port 8060 nicht verfügbar")):
        queue._dispatch_and_poll(job["id"])
        queue._dispatch_and_poll(job["id"])
    public=queue.get_job("video",job["id"])
    assert "8060" in public["last_service_error"]
    assert public["retry_count"]==1 and public["dispatch_attempts"]==2
    assert public["waiting_seconds"]>=0 and public["next_retry_at"]>public["waiting_since"]
    assert queue.QUEUE_FILE.is_file()


def test_queue_safe_last_error_redacts_sensitive_details():
    error=queue.ServiceError(503,"Service offline /Users/private/model token=secret prompt=private")
    result=queue.safe_service_error("video",error)
    assert "secret" not in result and "/Users/" not in result and "private" not in result
    assert "503" in result


def test_offline_video_requires_launchd_port_and_owned_process_verification():
    def stopped(command, **kwargs):
        return mock.Mock(returncode=113 if command[0]=="launchctl" else 1,stdout=b"")
    with mock.patch.object(runtime.subprocess,"run",side_effect=stopped), \
         mock.patch("process_identity.table",return_value={}):
        assert runtime.video_service_proven_stopped()
    with mock.patch.object(runtime.subprocess,"run",return_value=mock.Mock(returncode=0,stdout=b"")):
        assert not runtime.video_service_proven_stopped()


@pytest.mark.parametrize("proven",[False,True])
def test_image_runtime_only_allows_proven_stopped_video(tmp_path,proven):
    def requester(method,url,*args,**kwargs):
        if url.startswith(runtime.VIDEO_URL):raise OSError("offline")
        return {"ok":True,"loaded":False,"active_generation":False}
    with mock.patch.object(runtime,"video_service_proven_stopped",return_value=proven):
        if proven:
            with runtime.image_runtime(threading.Event(),requester=requester,lock_path=tmp_path/"lease",chat_loaded=lambda:False):
                pass
        else:
            with pytest.raises(runtime.ServiceUnavailable):
                with runtime.image_runtime(threading.Event(),requester=requester,lock_path=tmp_path/"lease",chat_loaded=lambda:False):
                    pass
