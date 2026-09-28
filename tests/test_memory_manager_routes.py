import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.memory_manager_routes import (
    inject_memory_manager_script,
    install_routes,
)


class MemoryManagerRouteTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        app = FastAPI()

        def agent_json_request(method, path, payload=None, timeout=10):
            self.calls.append({
                "method": method,
                "path": path,
                "payload": payload,
                "timeout": timeout,
            })
            if method == "GET" and path.startswith("/api/memory?"):
                return {"memories": []}
            if method == "POST":
                return {"memory": {"id": "m1", **(payload or {})}}
            if method == "PATCH":
                return {"memory": {"id": "m1", **(payload or {})}}
            if method == "DELETE":
                return {"ok": True}
            return {"context": ""}

        install_routes(app, agent_json_request)
        self.client = TestClient(app, base_url="http://localhost")
        self.addCleanup(self.client.close)

    def test_list_create_update_delete_are_proxied(self):
        response = self.client.get(
            "/api/mlx/memory?include_disabled=true&limit=700"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("include_disabled=true", self.calls[-1]["path"])
        self.assertIn("limit=700", self.calls[-1]["path"])

        response = self.client.post(
            "/api/mlx/memory",
            json={"text": "For coding I prefer Qwen3.8"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.calls[-1]["method"], "POST")

        response = self.client.patch(
            "/api/mlx/memory/m1",
            json={"pinned": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.calls[-1]["payload"], {"pinned": True})

        response = self.client.delete("/api/mlx/memory/m1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.calls[-1]["method"], "DELETE")

    def test_context_query_is_encoded_and_bounded(self):
        response = self.client.get(
            "/api/mlx/memory/context",
            params={"query": "Qwen coding", "limit": 99},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("query=Qwen+coding", self.calls[-1]["path"])
        self.assertIn("limit=12", self.calls[-1]["path"])

    def test_script_injection_is_idempotent_and_before_chat_runtime(self):
        html = (
            b"<html><body>"
            b'<script src="/assets/chat.js?v=20260926-shorts-progress"></script>'
            b"</body></html>"
        )
        injected = inject_memory_manager_script(html)
        self.assertIn(b"memory-manager.js", injected)
        self.assertLess(
            injected.index(b"memory-manager.js"),
            injected.index(b"/assets/chat.js"),
        )
        self.assertEqual(
            inject_memory_manager_script(injected).count(b"memory-manager.js"),
            1,
        )


if __name__ == "__main__":
    unittest.main()
