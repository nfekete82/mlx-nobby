"""The web image must forward Media Studio lineage routes to the host Agent."""
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend import app as web


def test_workflow_routes_forward_and_preserve_errors(monkeypatch):
    app = FastAPI()
    for route in web.app.router.routes:
        if getattr(route, "path", "").startswith("/api/library/workflows"):
            app.router.routes.append(route)
    client = TestClient(app)
    calls = []
    def forward(method, path, payload=None, timeout=10):
        calls.append((method, path, payload, timeout))
        if payload == {"fail": True}:
            raise HTTPException(422, "bad link")
        return {"version": 1, "links": {}}
    monkeypatch.setattr(web, "agent_json_request", forward)
    assert client.get("/api/library/workflows").json() == {"version": 1, "links": {}}
    payload = {"source_kind": "image", "source_id": "1791579990-f04fe5195fe0",
               "output_kind": "video", "output_id": "a" * 24}
    assert client.post("/api/library/workflows/links", json=payload).status_code == 200
    assert calls == [("GET", "/api/library/workflows", None, 30),
                     ("POST", "/api/library/workflows/links", payload, 30)]
    failed = client.post("/api/library/workflows/links", json={"fail": True})
    assert failed.status_code == 422


def test_workflow_routes_are_defined_exactly_once():
    expected = {("/api/library/workflows", "GET"),
                ("/api/library/workflows/links", "POST")}
    found = [(route.path, method) for route in web.app.router.routes
             for method in (getattr(route, "methods", None) or ())
             if (route.path, method) in expected]
    assert set(found) == expected
    assert len(found) == len(expected)
