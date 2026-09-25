from unittest import mock

from fastapi import HTTPException

from agent import shorts_jobs
from agent.shorts_planner import ShortProject


def project():
    return ShortProject.model_validate({
        "title": "Berlin in zehn Jahren",
        "duration": 20,
        "scenes": [
            {
                "id": f"scene-{index}",
                "duration": 5,
                "narration": f"Szene {index}",
                "video_prompt": f"Future Berlin scene {index}",
            }
            for index in range(1, 5)
        ],
    })


def configure_store(tmp_path, monkeypatch):
    directory = tmp_path / "shorts"
    monkeypatch.setattr(shorts_jobs, "SHORTS_DIRECTORY", directory)
    monkeypatch.setattr(shorts_jobs, "SHORTS_JOBS_FILE", directory / "jobs.json")
    with shorts_jobs._workers_lock:
        shorts_jobs._workers.clear()


class CompletedVideoAPI:
    def __init__(self):
        self.calls = []
        self.created = 0

    def __call__(self, method, path, payload=None, timeout=15):
        self.calls.append((method, path, payload, timeout))
        if method == "POST" and path == "/jobs":
            self.created += 1
            return {"id": f"{self.created:024x}", "status": "queued"}
        if method == "GET":
            child_id = path.rsplit("/", 1)[-1]
            return {
                "id": child_id,
                "status": "completed",
                "result": {"path": f"/videos/{child_id}.mp4"},
            }
        raise AssertionError((method, path))


def test_job_is_created_persistently(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(
        project(), chat_id="chat-one", run_id="run-one", chat_revision=3,
    )

    assert shorts_jobs.SHORTS_JOBS_FILE.is_file()
    stored = shorts_jobs.get_short_job(job["id"])
    assert stored["kind"] == "shorts"
    assert stored["project"]["aspect_ratio"] == "9:16"
    assert stored["current_scene"] == 0
    assert stored["scene_results"] == []
    assert stored["cancel_requested"] is False


def test_four_scenes_run_sequentially_and_finish(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    api = CompletedVideoAPI()
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")

    result = shorts_jobs.run_short_job(job["id"], request_fn=api, poll_interval=0)

    assert result["status"] == "video_completed"
    assert result["phase"] == "video_completed"
    assert result["current_scene"] == 4
    assert len(result["scene_results"]) == 4
    assert [call[:2] for call in api.calls] == [
        item
        for index in range(1, 5)
        for item in (("POST", "/jobs"), ("GET", f"/jobs/{index:024x}"))
    ]
    for index, call in enumerate(api.calls[::2]):
        payload = call[2]["payload"]
        assert payload["prompt"] == f"Future Berlin scene {index + 1}"
        assert payload["duration"] == 5
        assert payload["aspect_ratio"] == "9:16"


def test_child_id_is_persisted_before_polling(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    child_id = "a" * 24

    def request(method, path, payload=None, timeout=15):
        if method == "POST":
            return {"id": child_id, "status": "queued"}
        stored = shorts_jobs.get_short_job(job["id"])
        assert stored["active_video_job_id"] == child_id
        return {"id": child_id, "status": "failed", "error": "stop"}

    shorts_jobs.run_short_job(job["id"], request_fn=request, poll_interval=0)

    assert shorts_jobs.get_short_job(job["id"])["active_video_job_id"] == child_id


def test_resume_skips_completed_scene(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    api = CompletedVideoAPI()
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    first_child = "f" * 24
    shorts_jobs._update_job(
        job["id"],
        status="running",
        current_scene=0,
        scene_results=[{
            "scene_id": "scene-1", "duration": 5, "status": "completed",
            "video_job_id": first_child, "path": f"/videos/{first_child}.mp4",
        }],
    )

    result = shorts_jobs.run_short_job(job["id"], request_fn=api, poll_interval=0)

    assert result["status"] == "video_completed"
    assert api.created == 3
    assert [entry["scene_id"] for entry in result["scene_results"]] == [
        "scene-1", "scene-2", "scene-3", "scene-4",
    ]


def test_resume_polls_existing_child_before_starting_another(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    api = CompletedVideoAPI()
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    existing_child = "e" * 24
    shorts_jobs._update_job(
        job["id"], status="running", active_video_job_id=existing_child,
    )

    result = shorts_jobs.run_short_job(job["id"], request_fn=api, poll_interval=0)

    assert result["status"] == "video_completed"
    assert api.calls[0][:2] == ("GET", f"/jobs/{existing_child}")
    assert api.created == 3
    assert result["scene_results"][0]["video_job_id"] == existing_child


def test_resume_retries_existing_child_while_video_service_starts(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    api = CompletedVideoAPI()
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    existing_child = "9" * 24
    shorts_jobs._update_job(
        job["id"], status="running", active_video_job_id=existing_child,
    )
    attempts = 0

    def request(method, path, payload=None, timeout=15):
        nonlocal attempts
        if method == "GET" and attempts == 0:
            attempts += 1
            raise HTTPException(503, "Video-Service nicht erreichbar")
        return api(method, path, payload, timeout)

    with mock.patch.object(shorts_jobs.time, "sleep") as sleep:
        result = shorts_jobs.run_short_job(
            job["id"], request_fn=request, poll_interval=1,
        )

    assert result["status"] == "video_completed"
    assert sleep.call_count == 1
    assert api.calls[0][:2] == ("GET", f"/jobs/{existing_child}")


def test_child_failure_fails_short(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    child_id = "b" * 24

    def request(method, path, payload=None, timeout=15):
        if method == "POST":
            return {"id": child_id, "status": "queued"}
        return {"id": child_id, "status": "failed", "error": "LTX failed"}

    result = shorts_jobs.run_short_job(job["id"], request_fn=request, poll_interval=0)

    assert result["status"] == "failed"
    assert result["error"] == "LTX failed"
    assert result["finished_at"] is not None


def test_cancel_requests_active_video_cancellation(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    child_id = "c" * 24
    shorts_jobs._update_job(
        job["id"], status="running", active_video_job_id=child_id,
    )
    calls = []

    def request(method, path, payload=None, timeout=15):
        calls.append((method, path, payload, timeout))
        return {"id": child_id, "status": "cancelled"}

    result = shorts_jobs.cancel_short_job(job["id"], request_fn=request)

    assert calls == [("POST", f"/jobs/{child_id}/cancel", {}, 30)]
    assert result["status"] == "cancelled"
    assert result["cancel_requested"] is True
    assert result["finished_at"] is not None


def test_cancel_request_wins_over_concurrent_child_failure(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    child_id = "d" * 24

    def request(method, path, payload=None, timeout=15):
        if method == "POST" and path == "/jobs":
            return {"id": child_id, "status": "queued"}
        if method == "GET":
            shorts_jobs._update_job(job["id"], cancel_requested=True)
            return {"id": child_id, "status": "failed", "error": "cancel race"}
        return {"id": child_id, "status": "cancelled"}

    result = shorts_jobs.run_short_job(job["id"], request_fn=request, poll_interval=0)

    assert result["status"] == "cancelled"
    assert result["error"] is None


def test_resume_short_jobs_registers_only_active_jobs(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    queued = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    completed = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    shorts_jobs._update_job(
        completed["id"], status="video_completed", phase="video_completed",
    )

    with mock.patch.object(shorts_jobs, "start_short_job") as start:
        resumed = shorts_jobs.resume_short_jobs()

    assert resumed == [queued["id"]]
    start.assert_called_once_with(
        queued["id"], request_fn=None, poll_interval=1.0,
    )
