import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import shorts_studio_routes as agent_routes
from backend import shorts_studio_routes as backend_routes


class ShortsHistoryTests(unittest.TestCase):
    def make_job(
        self,
        job_id,
        *,
        created_at,
        status="completed",
        parent_job_id=None,
        title="Demo Short",
        voice="Nobby",
        scene_count=2,
        current_scene=2,
        final_path="/tmp/final.mp4",
    ):
        job = {
            "id": job_id,
            "kind": "shorts",
            "status": status,
            "phase": status,
            "created_at": created_at,
            "started_at": created_at + 1,
            "finished_at": created_at + 2 if status == "completed" else None,
            "current_scene": current_scene,
            "final_path": final_path if status == "completed" else None,
            "chat_id": "chat-1",
            "error": None,
            "project": {
                "title": title,
                "duration": 20,
                "voice": voice,
                "voice_speed": 1.0,
                "scenes": [
                    {"id": f"scene-{index}", "duration": 10}
                    for index in range(scene_count)
                ],
            },
        }
        if parent_job_id:
            job["parent_job_id"] = parent_job_id
        return job

    def test_history_groups_revisions_and_uses_latest_job(self):
        root_id = "a" * 24
        revision_id = "b" * 24
        other_id = "c" * 24
        jobs = {
            root_id: self.make_job(root_id, created_at=100, title="Berlin 2036"),
            revision_id: self.make_job(
                revision_id,
                created_at=200,
                parent_job_id=root_id,
                title="Berlin 2036 revised",
            ),
            other_id: self.make_job(
                other_id,
                created_at=300,
                status="running",
                title="Tokyo 2040",
                current_scene=1,
                final_path=None,
            ),
        }

        with mock.patch.object(agent_routes.shorts_jobs, "_load_jobs", return_value=jobs):
            result = agent_routes.list_short_history(limit=50)

        self.assertEqual(result["total"], 2)
        self.assertEqual([item["id"] for item in result["projects"]], [other_id, revision_id])

        revised = result["projects"][1]
        self.assertEqual(revised["root_job_id"], root_id)
        self.assertEqual(revised["revision_count"], 1)
        self.assertEqual(revised["title"], "Berlin 2036 revised")
        self.assertTrue(revised["has_video"])

        active = result["projects"][0]
        self.assertEqual(active["status"], "running")
        self.assertEqual(active["progress"], 0.5)
        self.assertFalse(active["has_video"])

    def test_history_limit_is_clamped(self):
        jobs = {
            f"{index:024x}": self.make_job(f"{index:024x}", created_at=index)
            for index in range(1, 5)
        }
        with mock.patch.object(agent_routes.shorts_jobs, "_load_jobs", return_value=jobs):
            result = agent_routes.list_short_history(limit=2)
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["limit"], 2)
        self.assertEqual(len(result["projects"]), 2)

    def test_agent_history_route_is_registered(self):
        app = FastAPI()
        agent_routes.install_routes(app)
        paths = {route.path for route in app.routes}
        self.assertIn("/api/shorts-jobs", paths)
        self.assertIn("/api/shorts/jobs/{job_id}/scenes/{scene_id}/revise", paths)

    def test_backend_history_proxy_uses_agent_endpoint(self):
        calls = []

        def requester(method, path, payload=None, timeout=10):
            calls.append((method, path, payload, timeout))
            return {"projects": [], "total": 0, "limit": 12}

        app = FastAPI()
        backend_routes.install_routes(app, requester)
        client = TestClient(app)
        response = client.get("/api/mlx/shorts-jobs?limit=12")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["limit"], 12)
        self.assertEqual(
            calls,
            [("GET", "/api/shorts-jobs?limit=12", None, 15)],
        )


if __name__ == "__main__":
    unittest.main()
