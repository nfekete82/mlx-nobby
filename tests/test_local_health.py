"""Offline tests for the sanitized read-only local health report."""
import importlib.util
from pathlib import Path

script = Path(__file__).resolve().parents[1] / "scripts/local-health.py"
spec = importlib.util.spec_from_file_location("mlx_local_health", script)
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


def test_revision_counts_are_safe():
    data = {
        "ok": False, "stale_services": ["images"], "unknown_services": ["video"],
        "services": [{"error": "private local path"}],
    }
    assert health.revision_summary(data) == {
        "reachable": True, "stale_count": 1, "unknown_count": 1
    }
    assert health.revision_summary({"ok": True})["reachable"] is False


def test_queue_returns_only_counts():
    data = {
        "jobs": [{"id": "secret", "prompt": "sensitive input"}],
        "active_count": 1, "waiting_count": 0,
    }
    assert health.queue_summary(data) == {"reachable": True, "active": 1, "waiting": 0}
    assert not health.queue_summary({"active_count": True, "waiting_count": 0})["reachable"]


def test_collect_only_uses_get_and_discards_private_payload(monkeypatch):
    monkeypatch.setattr(health, "git_summary", lambda: {
        "branch": "test", "commit": "abc", "tracked_changes": 0,
        "untracked_files": 0, "ahead": 0, "behind": 0, "upstream_configured": True
    })
    requests = []

    def request(port, path):
        requests.append((port, path))
        if path == "/api/system/revisions":
            return {"stale_services": [], "unknown_services": []}, None
        if path == "/api/system/job-queue":
            return {"active_count": 0, "waiting_count": 0, "prompt": "private text"}, None
        return {"ok": True, "model": "/Users/private/Models"}, None

    report = health.collect(request=request)
    assert report["queue"]["active"] == 0
    assert all(port in {8090, 8010, 8030, 8060, 8040, 8020, 8050} for port, _ in requests)
    assert "private text" not in str(report)
    assert "/Users/private" not in str(report)
    assert not health.findings(report)[0]


def test_required_and_optional_services():
    report = {
        "git": {"tracked_changes": 0, "behind": 0},
        "services": [
            {"name": "Images", "port": 8030, "reachable": False, "required": True},
            {"name": "Router", "port": 8040, "reachable": False, "required": False},
        ],
        "revisions": {"reachable": True, "stale_count": 0, "unknown_count": 0},
        "queue": {"reachable": True, "active": 0, "waiting": 0},
    }
    failures, warnings = health.findings(report)
    assert len(failures) == 1 and len(warnings) == 1
    assert len(health.findings(report, strict=True)[0]) == 2


def test_unhealthy_http_200_is_not_reported_as_healthy():
    assert health.service_healthy({"ok": False, "status": "failed"}, None) is False
    assert health.service_healthy({"status": "error"}, None) is False
    assert health.service_healthy({"status": "busy", "ok": True}, None) is True
    assert health.service_healthy({"status": "ok"}, None) is True
    assert health.service_healthy({"ok": True}, "HTTP 503") is False


def test_runtime_opt_in_requires_readiness(monkeypatch):
    monkeypatch.setattr(health, "git_summary", lambda: {
        "branch": "test", "commit": "abc", "tracked_changes": 0,
        "untracked_files": 0, "ahead": 0, "behind": 0, "upstream_configured": True,
    })

    def request(port, path):
        if port == 8000:
            return None, "unreachable"
        if path == "/api/system/revisions":
            return {"stale_services": [], "unknown_services": []}, None
        if path == "/api/system/job-queue":
            return {"active_count": 0, "waiting_count": 0}, None
        return {"ok": True}, None

    ordinary = health.collect(request=request)
    failures, _ = health.findings(ordinary)
    assert not failures
    explicit = health.collect(include_runtime=True, request=request)
    assert explicit["services"][-1]["required"] is True
    failures, _ = health.findings(explicit)
    assert "MLX runtime (port 8000) unreachable" in failures
