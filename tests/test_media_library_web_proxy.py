"""Regression: browser-facing Library 3.0 requests must be proxied to Agent.

The Agent can expose the organization API while the Docker web application
still returns 404. The browser's Library refresh fetches both concurrently.
"""
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from backend import app as web


def _routes_client():
    app = FastAPI()
    for route in web.app.router.routes:
        if getattr(route, "path", "").startswith("/api/library/organize"):
            app.router.routes.append(route)
    return TestClient(app)


def test_browser_library_organization_proxy_routes_all_methods(monkeypatch):
    calls = []

    def forwarded(method, path, payload=None, timeout=10):
        calls.append((method, path, payload, timeout))
        return {"ok": True, "path": path}

    monkeypatch.setattr(web, "agent_json_request", forwarded)
    client = _routes_client()
    assert client.get("/api/library/organize").status_code == 200
    assert client.get("/api/library/organize").json()["path"] == "/api/library/organize"

    created = client.post("/api/library/organize/collections", json={"name": "Reisen"})
    assert created.status_code == 200
    removed = client.delete("/api/library/organize/collections/" + "a" * 16)
    assert removed.status_code == 200
    payload = {
        "items": [{"kind": "image", "id": "1791579990-f04fe5195fe0"}],
        "operation": "favorite",
    }
    batch = client.post("/api/library/organize/batch", json=payload)
    assert batch.status_code == 200
    assert calls == [
        ("GET", "/api/library/organize", None, 30),
        ("GET", "/api/library/organize", None, 30),
        ("POST", "/api/library/organize/collections", {"name": "Reisen"}, 30),
        ("DELETE", "/api/library/organize/collections/" + "a" * 16, None, 30),
        ("POST", "/api/library/organize/batch", payload, 60),
    ]


def test_browser_library_organization_proxy_keeps_agent_errors(monkeypatch):
    def upstream(_method, _path, payload=None, timeout=10):
        raise HTTPException(status_code=422, detail="Invalid media asset")

    monkeypatch.setattr(web, "agent_json_request", upstream)
    client = _routes_client()
    result = client.post("/api/library/organize/batch", json={"items": []})
    assert result.status_code == 422
    assert result.json()["detail"] == "Invalid media asset"


def test_browser_organization_routes_are_registered_once():
    expected = {
        ("/api/library/organize", "GET"),
        ("/api/library/organize/collections", "POST"),
        ("/api/library/organize/collections/{collection_id}", "DELETE"),
        ("/api/library/organize/batch", "POST"),
    }
    actual = [
        (route.path, method)
        for route in web.app.router.routes
        for method in (getattr(route, "methods", None) or ())
        if (route.path, method) in expected
    ]
    assert set(actual) == expected
    assert len(actual) == len(expected), "No ambiguous duplicate proxy routes"
