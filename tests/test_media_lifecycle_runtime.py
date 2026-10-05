from agent import media_lifecycle_runtime


def test_register_completed_chat_video_is_temporary(monkeypatch):
    calls = []
    monkeypatch.setattr(media_lifecycle_runtime, "_shorts_references_job", lambda _job_id: False)
    monkeypatch.setattr(
        media_lifecycle_runtime.media_lifecycle,
        "register",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    media_lifecycle_runtime._register_completed(
        "a" * 24,
        {
            "id": "a" * 24,
            "kind": "video",
            "status": "completed",
            "chat_id": "chat-1",
            "result": {
                "id": "b" * 24,
                "path": "/tmp/video.mp4",
            },
        },
    )

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("video", "b" * 24, "/tmp/video.mp4")
    assert kwargs["persistent"] is False
    assert kwargs["owner"] == "chat"


def test_register_completed_shorts_video_is_persistent(monkeypatch):
    calls = []
    monkeypatch.setattr(media_lifecycle_runtime, "_shorts_references_job", lambda _job_id: True)
    monkeypatch.setattr(
        media_lifecycle_runtime.media_lifecycle,
        "register",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    media_lifecycle_runtime._register_completed(
        "c" * 24,
        {
            "id": "c" * 24,
            "kind": "video",
            "status": "completed",
            "chat_id": "chat-1",
            "result": {
                "id": "d" * 24,
                "path": "/tmp/project.mp4",
            },
        },
    )

    assert calls[0][1]["persistent"] is True
    assert calls[0][1]["owner"] == "project"


def test_register_project_prefix_is_persistent(monkeypatch):
    calls = []
    monkeypatch.setattr(media_lifecycle_runtime, "_shorts_references_job", lambda _job_id: False)
    monkeypatch.setattr(
        media_lifecycle_runtime.media_lifecycle,
        "register",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    media_lifecycle_runtime._register_completed(
        "e" * 24,
        {
            "kind": "image",
            "status": "completed",
            "chat_id": "project:campaign-1",
            "result": {
                "id": "1234567890-abcdef123456",
                "path": "/tmp/project.png",
            },
        },
    )

    assert calls[0][1]["persistent"] is True


def test_talking_photo_motion_child_is_temporary(monkeypatch):
    calls = []
    monkeypatch.setattr(media_lifecycle_runtime, "_shorts_references_job", lambda _job_id: False)
    monkeypatch.setattr(
        media_lifecycle_runtime.media_lifecycle,
        "register",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    media_lifecycle_runtime._register_completed(
        "f" * 24,
        {
            "kind": "video",
            "status": "completed",
            "chat_id": "talking-photo:" + "1" * 24,
            "result": {
                "id": "2" * 24,
                "path": "/tmp/motion.mp4",
            },
        },
    )

    assert calls[0][1]["persistent"] is False
    assert calls[0][1]["owner"] == "talking-photo-intermediate"


def test_incomplete_job_is_not_registered(monkeypatch):
    calls = []
    monkeypatch.setattr(
        media_lifecycle_runtime.media_lifecycle,
        "register",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    media_lifecycle_runtime._register_completed(
        "3" * 24,
        {"kind": "video", "status": "failed", "result": None},
    )

    assert calls == []
