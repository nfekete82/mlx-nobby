import io
import unittest
from email.message import Message
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import service_proxy
from local_security import LocalRequestGuard
from service_identity import service_identity


class RevisionResponse(io.BytesIO):
    def __init__(self, revision=None, started_at="2026-09-27T17:00:00+00:00"):
        super().__init__(b"{}")
        self.status = 200
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        if revision is not None:
            self.headers["X-MLX-Nobby-Revision"] = revision
        if started_at is not None:
            self.headers["X-MLX-Nobby-Started-At"] = started_at

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class ServiceRevisionTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.add_middleware(LocalRequestGuard)
        service_proxy.install_routes(self.app, lambda: 8123, MagicMock())
        self.client = TestClient(self.app, base_url="http://localhost")
        self.addCleanup(self.client.close)

    def test_local_guard_exposes_process_revision_headers(self):
        response = self.client.post(
            "/api/models/validate-local",
            json={"path": ""},
        )

        identity = service_identity()
        self.assertEqual(
            response.headers["X-MLX-Nobby-Revision"],
            identity["revision"],
        )
        self.assertEqual(
            response.headers["X-MLX-Nobby-Started-At"],
            identity["started_at"],
        )

    def test_revision_endpoint_reports_stale_and_unknown_services(self):
        current = service_identity()["revision"]

        def open_local(request, timeout):
            url = request.full_url
            if ":8090/" in url:
                return RevisionResponse(current)
            if ":8020/" in url:
                return RevisionResponse("deadbeef1234")
            if ":8030/" in url:
                return RevisionResponse(current)
            if ":8050/" in url:
                return RevisionResponse(current)
            if ":8060/" in url:
                return RevisionResponse(None)
            raise AssertionError(f"Unexpected revision probe: {url}")

        with patch.object(
            service_proxy.urllib.request,
            "urlopen",
            side_effect=open_local,
        ):
            response = self.client.get("/api/system/revisions")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertFalse(payload["consistent"])
        self.assertEqual(payload["stale_services"], ["embeddings"])
        self.assertEqual(payload["unknown_services"], ["video"])
        self.assertEqual(payload["services"][0]["service"], "agent")
        self.assertEqual(payload["services"][0]["revision"], current)


if __name__ == "__main__":
    unittest.main()
