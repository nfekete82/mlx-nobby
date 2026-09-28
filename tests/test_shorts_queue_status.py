from agent import shorts_jobs
from agent import shorts_consistency_runtime


def test_dispatching_is_a_valid_active_video_status():
    assert "dispatching" in shorts_jobs.VIDEO_ACTIVE_STATUSES


def test_consistency_runtime_uses_the_same_video_status_contract():
    assert shorts_consistency_runtime.VIDEO_ACTIVE_STATUSES is shorts_jobs.VIDEO_ACTIVE_STATUSES
    assert "dispatching" in shorts_consistency_runtime.VIDEO_ACTIVE_STATUSES
