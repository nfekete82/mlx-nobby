from fastapi import FastAPI

from agent import system_health_routes as health
from backend import system_health_routes as web_health


def setup_function():
    with health._progress_lock:
        health._progress_observations.clear()


def test_parse_elapsed_supports_bsd_ps_formats():
    assert health._parse_elapsed("03:04") == 184
    assert health._parse_elapsed("01:02:03") == 3723
    assert health._parse_elapsed("2-01:02:03") == 176523
    assert health._parse_elapsed("") is None
    assert health._parse_elapsed("invalid") is None


def test_model_from_health_prefers_running_model_and_loaded_models():
    assert health._model_from_health({
        "running_model": "juggernaut-xl",
        "default_model": "auto",
    }) == "juggernaut-xl"

    assert health._model_from_health({
        "data": [
            {"id": "one", "loaded": False},
            {"id": "two", "loaded": True},
        ]
    }) == "two"


def test_stuck_job_requires_unchanged_progress_for_threshold():
    snapshot = {
        "jobs": [{
            "id": "a" * 24,
            "kind": "image",
            "title": "Portrait",
            "queue_status": "running",
            "status": "running",
            "phase": "running",
            "progress": 0.25,
            "current_step": 10,
            "total_steps": 40,
        }]
    }

    assert health._observe_stuck_jobs(snapshot, now=100.0) == []
    stuck = health._observe_stuck_jobs(
        snapshot,
        now=100.0 + health.STUCK_SECONDS + 1,
    )
    assert len(stuck) == 1
    assert stuck[0]["id"] == "a" * 24
    assert stuck[0]["idle_seconds"] >= health.STUCK_SECONDS

    snapshot["jobs"][0]["current_step"] = 11
    assert health._observe_stuck_jobs(
        snapshot,
        now=100.0 + health.STUCK_SECONDS + 2,
    ) == []


def test_system_health_route_registration_is_idempotent():
    app = FastAPI()
    health.install_routes(app)
    health.install_routes(app)
    paths = [getattr(route, "path", None) for route in app.router.routes]
    assert paths.count("/api/system/health-v1") == 1
    assert paths.count("/api/system/services/{service_id}/restart") == 1
    assert paths.count("/api/system/self-heal") == 1


def test_web_proxy_routes_forward_to_agent():
    calls = []

    def agent_json_request(method, path, payload=None, timeout=10):
        calls.append((method, path, payload, timeout))
        return {"ok": True}

    app = FastAPI()
    web_health.install_routes(app, agent_json_request)
    routes = {
        route.path: route.endpoint
        for route in app.router.routes
        if getattr(route, "path", "").startswith("/api/mlx/system")
    }

    assert routes["/api/mlx/system/health-v1"]() == {"ok": True}
    assert calls[-1][:2] == ("GET", "/api/system/health-v1")

    assert routes["/api/mlx/system/services/{service_id}/restart"]("speech") == {"ok": True}
    assert calls[-1][0] == "POST"
    assert calls[-1][1] == "/api/system/services/speech/restart"

    assert routes["/api/mlx/system/self-heal"]() == {"ok": True}
    assert calls[-1][1] == "/api/system/self-heal"


def test_system_health_script_injection_is_idempotent():
    source = b'<html><body><script src="/assets/chat.js?v=20260926-shorts-progress"></script></body></html>'
    injected = web_health.inject_system_health_script(source)
    assert web_health.SYSTEM_HEALTH_SCRIPT in injected
    assert injected.index(web_health.SYSTEM_HEALTH_SCRIPT) < injected.index(web_health.CHAT_SCRIPT_MARKER)
    assert web_health.inject_system_health_script(injected) == injected
