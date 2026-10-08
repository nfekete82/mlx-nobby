from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

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


def test_cached_builder_coalesces_concurrent_cache_misses(monkeypatch):
    module, calls = fake_health_module()
    performance.invalidate()
    monkeypatch.setattr(performance, "CACHE_TTL_SECONDS", 60.0)

    started = threading.Event()
    release = threading.Event()
    original_build = performance._build_snapshot

    def delayed_build(health_module):
        started.set()
        assert release.wait(5), "Health probe should have been released"
        return original_build(health_module)

    monkeypatch.setattr(performance, "_build_snapshot", delayed_build)
    builder = performance._cached_builder(module)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(builder) for _ in range(8)]
        try:
            assert started.wait(2)
        finally:
            release.set()
        snapshots = [future.result(timeout=5) for future in futures]

    assert len(calls) == 3  # One sweep, not eight overlapping sweeps.
    assert all(result == snapshots[0] for result in snapshots)
    assert len({id(result) for result in snapshots}) == 8


def test_invalidate_during_probe_is_nonblocking_and_discards_stale_result(monkeypatch):
    module, _ = fake_health_module()
    performance.invalidate()
    monkeypatch.setattr(performance, "CACHE_TTL_SECONDS", 60.0)

    started = threading.Event()
    release = threading.Event()
    invalidated = threading.Event()
    build_versions = []
    results = []
    failures = []

    def delayed_build(_health_module):
        version = len(build_versions) + 1
        build_versions.append(version)
        if version == 1:
            started.set()
            assert release.wait(5), "Health probe should have been released"
        return {"version": version}

    def read_snapshot():
        try:
            results.append(performance._cached_builder(module)())
        except BaseException as exc:
            failures.append(exc)

    monkeypatch.setattr(performance, "_build_snapshot", delayed_build)
    worker = threading.Thread(target=read_snapshot, daemon=True)
    invalidator = threading.Thread(
        target=lambda: (performance.invalidate(), invalidated.set()),
        daemon=True,
    )
    worker.start()
    try:
        assert started.wait(2)
        invalidator.start()
        # Invalidation must not wait for slow subprocess/network health probes.
        assert invalidated.wait(2)
    finally:
        release.set()
        worker.join(timeout=5)
        if invalidator.ident is not None:
            invalidator.join(timeout=5)

    assert not worker.is_alive()
    assert not invalidator.is_alive()
    assert failures == []
    assert build_versions == [1, 2]
    assert results == [{"version": 2}]


def test_failed_probe_releases_single_flight_waiters(monkeypatch):
    module, _ = fake_health_module()
    performance.invalidate()
    monkeypatch.setattr(performance, "CACHE_TTL_SECONDS", 60.0)
    original_build = performance._build_snapshot
    attempts = 0

    def flaky_build(health_module):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient health probe failure")
        return original_build(health_module)

    monkeypatch.setattr(performance, "_build_snapshot", flaky_build)
    builder = performance._cached_builder(module)

    with pytest.raises(RuntimeError, match="transient health probe failure"):
        builder()

    result = builder()
    assert result["ok"] is True
    assert attempts == 2
