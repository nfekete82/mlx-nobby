import unittest
from unittest import mock

from fastapi.testclient import TestClient

import agent.app as agent_app


class LifecycleStatusTests(unittest.TestCase):

    def setUp(self):
        agent_app._set_system_lifecycle_state(
            state="idle",
            action=None,
            phase="idle",
            message="",
            current=0,
            total=0,
            error=None,
        )

        self.client = TestClient(
            agent_app.app,
            base_url="http://127.0.0.1",
            headers={
                "Host": "127.0.0.1",
                "Origin": "http://127.0.0.1",
            },
        )

    def test_lifecycle_status_is_idle_by_default(self):
        response = self.client.get(
            "/api/system/lifecycle"
        )

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertEqual(
            data["state"],
            "idle",
        )

        self.assertIsNone(
            data["action"],
        )

    def test_restart_marks_lifecycle_as_accepted(self):
        with mock.patch.object(
            agent_app,
            "_launch_system_lifecycle_helper",
        ):
            response = self.client.post(
                "/api/system/restart-all"
            )

        self.assertEqual(
            response.status_code,
            202,
        )

        status = self.client.get(
            "/api/system/lifecycle"
        ).json()

        self.assertEqual(
            status["action"],
            "restart-all",
        )

        self.assertEqual(
            status["state"],
            "accepted",
        )

    def test_reboot_marks_lifecycle_as_accepted(self):
        with mock.patch.object(
            agent_app,
            "_launch_system_lifecycle_helper",
        ):
            response = self.client.post(
                "/api/system/reboot"
            )

        self.assertEqual(
            response.status_code,
            202,
        )

        status = self.client.get(
            "/api/system/lifecycle"
        ).json()

        self.assertEqual(
            status["action"],
            "reboot",
        )

        self.assertEqual(
            status["state"],
            "accepted",
        )

    def test_shutdown_ai_marks_lifecycle_as_accepted(self):
        with mock.patch.object(agent_app, "_launch_system_lifecycle_helper"):
            response = self.client.post("/api/system/shutdown-ai")

        self.assertEqual(response.status_code, 202)
        status = self.client.get("/api/system/lifecycle").json()
        self.assertEqual(status["action"], "shutdown-ai")
        self.assertEqual(status["state"], "accepted")

    def test_lifecycle_status_contains_progress_contract(self):
        response = self.client.get(
            "/api/system/lifecycle"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        data = response.json()

        required = {
            "action",
            "state",
            "phase",
            "current",
            "total",
            "message",
            "error",
        }

        self.assertTrue(
            required.issubset(data),
            required - set(data),
        )


    def test_lifecycle_progress_can_be_updated(self):
        response = self.client.post(
            "/api/system/lifecycle/progress",
            json={
                "action": "restart-all",
                "state": "running",
                "phase": "router",
                "current": 3,
                "total": 6,
                "message": "Router wird neu gestartet.",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        status = self.client.get(
            "/api/system/lifecycle"
        )

        self.assertEqual(
            status.status_code,
            200,
        )

        data = status.json()

        self.assertEqual(
            data["action"],
            "restart-all",
        )
        self.assertEqual(
            data["state"],
            "running",
        )
        self.assertEqual(
            data["phase"],
            "router",
        )
        self.assertEqual(
            data["current"],
            3,
        )
        self.assertEqual(
            data["total"],
            6,
        )
        self.assertEqual(
            data["message"],
            "Router wird neu gestartet.",
        )
        self.assertIsNone(
            data["error"]
        )

    def test_lifecycle_can_be_marked_completed(self):
        response = self.client.post(
            "/api/system/lifecycle/progress",
            json={
                "action": "restart-all",
                "state": "completed",
                "phase": "complete",
                "current": 6,
                "total": 6,
                "message": "Alle Dienste wurden neu gestartet.",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        data = self.client.get(
            "/api/system/lifecycle"
        ).json()

        self.assertEqual(
            data["state"],
            "completed",
        )
        self.assertEqual(
            data["current"],
            6,
        )
        self.assertEqual(
            data["total"],
            6,
        )
        self.assertEqual(
            data["phase"],
            "complete",
        )

    def test_lifecycle_can_be_marked_failed(self):
        response = self.client.post(
            "/api/system/lifecycle/progress",
            json={
                "action": "rebuild-all",
                "state": "failed",
                "phase": "web",
                "current": 1,
                "total": 7,
                "message": "Web-Rebuild fehlgeschlagen.",
                "error": "docker compose build failed",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        data = self.client.get(
            "/api/system/lifecycle"
        ).json()

        self.assertEqual(
            data["state"],
            "failed",
        )
        self.assertEqual(
            data["phase"],
            "web",
        )
        self.assertEqual(
            data["error"],
            "docker compose build failed",
        )

    def test_lifecycle_progress_rejects_invalid_state(self):
        response = self.client.post(
            "/api/system/lifecycle/progress",
            json={
                "action": "restart-all",
                "state": "banana",
                "phase": "router",
                "current": 3,
                "total": 6,
                "message": "Invalid.",
            },
        )

        self.assertEqual(
            response.status_code,
            422,
        )


if __name__ == "__main__":
    unittest.main()
