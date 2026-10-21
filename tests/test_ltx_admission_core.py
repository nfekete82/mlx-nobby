"""CPU-only regressions for the dormant LTX admission building blocks."""
import json
import urllib.error
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ltx_lab.admission import AdmissionDenied, AdmissionMiddleware, Gate
from ltx_lab import admission, exclusive
from ltx_lab.queue_admission import stored_blockers


@pytest.fixture
def gate(tmp_path):
    return Gate(tmp_path / "private-gate")


def test_existing_request_prevents_exclusive(gate):
    token = gate.ticket()
    try:
        with pytest.raises(AdmissionDenied, match="Existing requests/jobs"):
            with gate.exclusive("not-created"):
                pytest.fail("exclusive should not enter")
        assert gate.state()["status"] == "idle"
    finally:
        token.close()


def test_exclusive_denies_new_requests_then_recovers(gate):
    app = FastAPI()
    @app.post("/infer")
    def infer():
        return {"ok": True}
    client = TestClient(AdmissionMiddleware(app, role="video", gate=gate))
    assert client.post("/infer").status_code == 200
    with gate.exclusive("mock") as (_, complete):
        assert client.post("/infer").status_code == 423
        assert client.get("/lab/admission").status_code == 200
        complete()
    assert client.post("/infer").status_code == 200


def test_restore_token_only_allows_restricted_route(gate):
    app = FastAPI()
    @app.post("/chat/completions")
    def restore():
        return {"choices": [{"message": {"content": "OK"}}]}
    @app.post("/jobs")
    def jobs():
        return {"ok": True}
    client = TestClient(AdmissionMiddleware(app, role="chat", gate=gate))
    with gate.exclusive("mock") as (creds, complete):
        headers = {"X-LTX-Lab-Session": creds["secret"]}
        assert client.post("/chat/completions", headers=headers).status_code == 200
        assert client.post("/jobs", headers=headers).status_code == 423
        assert creds["secret"] not in client.get("/lab/admission").text
        complete()


def test_missing_admission_endpoint_blocks_benchmark(gate):
    def missing(*_args, **_kwargs):
        raise urllib.error.HTTPError("http://127.0.0.1", 404, "not deployed", None, None)
    with pytest.raises(AdmissionDenied, match="proof unavailable"):
        exclusive.verify_services(gate, read=missing)
    assert gate.state()["status"] == "idle"


def test_unverified_identity_cannot_admit(gate):
    def fake(method, url):
        port = int(url.split(":")[2].split("/")[0])
        return {"protocol": admission.PROTOCOL, "gate": gate.identity(),
                "role": exclusive.PORTS[port], "pid": 456, "offline": True,
                "thread_tracking": True, "implementation": "WRONG-BUILD",
                "job_blockers": []}
    with pytest.raises(AdmissionDenied, match="Unverified"):
        exclusive.verify_services(gate, read=fake, inspect=lambda *_: "p456")


def test_persisted_jobs_block_and_corruption_fails_closed(tmp_path):
    path=tmp_path/"jobs.json"
    path.write_text(json.dumps({"a":{"status":"running"},"b":{"status":"completed"}}))
    assert [x["id"] for x in stored_blockers(path,"batch")] == ["a"]
    path.write_text("corrupt")
    with pytest.raises(ValueError):
        stored_blockers(path,"batch")


def test_failed_exclusive_keeps_durable_recovery_fence(gate):
    with pytest.raises(RuntimeError, match="aborted"):
        with gate.exclusive("mock"):
            raise RuntimeError("aborted")
    assert gate.state()["status"] == "recovery_required"
    with pytest.raises(AdmissionDenied):
        gate.ticket()
