import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.memory_manager_routes import inject_memory_manager_script, install_routes


class MemoryManagerConsolidationRouteTests(unittest.TestCase):
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
            if path == "/api/memory/consolidation-status":
                return {"enabled": True, "events": 3, "disabled_memories": 2}
            if path.startswith("/api/memory/consolidations?"):
                return {"consolidations": []}
            if path == "/api/memory/consolidate":
                return {"changed": True, "processed": 4, "absorbed": 1}
            if path.startswith("/api/memory?"):
                return {"memories": []}
            return {"ok": True}

        install_routes(app, agent_json_request)
        self.client = TestClient(app, base_url="http://localhost")
        self.addCleanup(self.client.close)

    def test_consolidation_status_and_history_are_proxied(self):
        response = self.client.get("/api/mlx/memory/consolidation-status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.calls[-1]["path"], "/api/memory/consolidation-status")

        response = self.client.get(
            "/api/mlx/memory/consolidations",
            params={"limit": 5000},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("limit=1000", self.calls[-1]["path"])

    def test_bulk_consolidation_uses_longer_timeout(self):
        response = self.client.post(
            "/api/mlx/memory/consolidate",
            json={"limit": 500},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.calls[-1]["method"], "POST")
        self.assertEqual(self.calls[-1]["path"], "/api/memory/consolidate")
        self.assertEqual(self.calls[-1]["payload"], {"limit": 500})
        self.assertEqual(self.calls[-1]["timeout"], 120)

    def test_both_memory_manager_modules_are_injected_once_before_chat(self):
        html = (
            b"<html><body>"
            b'<script src="/assets/chat.js?v=20260926-shorts-progress"></script>'
            b"</body></html>"
        )
        injected = inject_memory_manager_script(html)
        self.assertEqual(injected.count(b"memory-manager.js"), 1)
        self.assertEqual(injected.count(b"memory-manager-consolidation.js"), 1)
        self.assertLess(
            injected.index(b"memory-manager-consolidation.js"),
            injected.index(b"/assets/chat.js"),
        )
        reinjected = inject_memory_manager_script(injected)
        self.assertEqual(reinjected.count(b"memory-manager.js"), 1)
        self.assertEqual(reinjected.count(b"memory-manager-consolidation.js"), 1)


if __name__ == "__main__":
    unittest.main()
