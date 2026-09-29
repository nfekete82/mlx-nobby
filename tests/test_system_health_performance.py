from types import SimpleNamespace

from agent import system_health_performance as performance


def fake_health_module():
    calls = []

    def service_snapshot(spec):
        calls.append(spec["id"])
        return {
            "id": spec["id"],
            "name": spec["id"],
            "status": "healthy",
            "rss_bytes": 1024,
        }

    media_queue = SimpleNamespace(
        snapshot=lambda limit=40: {
            "active_count": 1,
            "waiting_count": 2,
            "runtime": {"owner": "test"},
            "jobs": [],
        }
    )

    module = SimpleNamespace(
        SERVICE_SPECS=(
            {"id": "runtime"},
            {"id": "images"},
            {"id": "speech"},
        ),
        STUCK_SECONDS=90,
        _service_snapshot=service_snapshot,
        _observe_stuck_jobs=lambda _snapshot: [],
        media_queue=media_queue,
    )
    return module, calls


def test_build_snapshot_preserves_health_shape():
    module, calls = fake_health_module()

    snapshot = performance._build_snapshot(module)

    assert sorted(calls) == ["images", "runtime", "speech"]
    assert snapshot["ok"] is True
    assert snapshot["summary"]["healthy"] == 3
    assert snapshot["summary"]["tracked_rss_bytes"] == 3 * 1024
    assert snapshot["summary"]["active_media_jobs"] == 1
    assert snapshot["summary"]["waiting_media_jobs"] == 2
    assert snapshot["media_queue"]["runtime"] == {"owner": "test"}


def test_cached_builder_reuses_snapshot_and_returns_copies(monkeypatch):
    module, calls = fake_health_module()
    performance.invalidate()
    monkeypatch.setattr(performance, "CACHE_TTL_SECONDS", 60.0)

    builder = performance._cached_builder(module)
    first = builder()
    second = builder()

    assert len(calls) == 3
    assert first == second
    assert first is not second

    second["services"][0]["status"] = "down"
    third = builder()

    assert third["services"][0]["status"] == "healthy"
    assert len(calls) == 3
