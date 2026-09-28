from pathlib import Path
import tempfile
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
            "error": "render failed" if status == "failed" else None,
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

    def test_delete_project_removes_full_revision_chain_and_owned_directories(self):
        root_id = "a" * 24
        revision_id = "b" * 24
        store = {
            root_id: self.make_job(root_id, created_at=100),
            revision_id: self.make_job(
                revision_id,
                created_at=200,
                parent_job_id=root_id,
            ),
        }

        def load_jobs():
            return dict(store)

        def save_jobs(updated):
            store.clear()
            store.update(updated)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for job_id in store:
                directory = root / job_id
                directory.mkdir()
                (directory / "final.mp4").write_bytes(b"video")

            with (
                mock.patch.object(agent_routes.shorts_jobs, "SHORTS_DIRECTORY", root),
                mock.patch.object(agent_routes.shorts_jobs, "_load_jobs", side_effect=load_jobs),
                mock.patch.object(agent_routes.shorts_jobs, "_save_jobs", side_effect=save_jobs),
                mock.patch.object(agent_routes.shorts_jobs, "_workers", {}),
            ):
                result = agent_routes.delete_short_project(revision_id)

            self.assertEqual(store, {})
            self.assertEqual(result["root_job_id"], root_id)
            self.assertEqual(result["deleted_jobs"], 2)
            self.assertEqual(result["cleanup_errors"], [])
            self.assertFalse((root / root_id).exists())
            self.assertFalse((root / revision_id).exists())

    def test_delete_project_rejects_active_revision_chain(self):
        root_id = "a" * 24
        revision_id = "b" * 24
        jobs = {
            root_id: self.make_job(root_id, created_at=100),
            revision_id: self.make_job(
                revision_id,
                created_at=200,
                status="running",
                parent_job_id=root_id,
                final_path=None,
            ),
        }

        with (
            mock.patch.object(agent_routes.shorts_jobs, "_load_jobs", return_value=jobs),
            mock.patch.object(agent_routes.shorts_jobs, "_save_jobs") as save_jobs,
            mock.patch.object(agent_routes.shorts_jobs, "_workers", {}),
        ):
            with self.assertRaisesRegex(ValueError, "cancelled before deletion"):
                agent_routes.delete_short_project(root_id)

        save_jobs.assert_not_called()

    def test_delete_failed_projects_only_removes_failed_latest_projects(self):
        failed_root = "a" * 24
        failed_revision = "b" * 24
        completed_id = "c" * 24
        store = {
            failed_root: self.make_job(failed_root, created_at=100),
            failed_revision: self.make_job(
                failed_revision,
                created_at=200,
                status="failed",
                parent_job_id=failed_root,
                final_path=None,
            ),
            completed_id: self.make_job(completed_id, created_at=300),
        }

        def load_jobs():
            return dict(store)

        def save_jobs(updated):
            store.clear()
            store.update(updated)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for job_id in store:
                (root / job_id).mkdir()

            with (
                mock.patch.object(agent_routes.shorts_jobs, "SHORTS_DIRECTORY", root),
                mock.patch.object(agent_routes.shorts_jobs, "_load_jobs", side_effect=load_jobs),
                mock.patch.object(agent_routes.shorts_jobs, "_save_jobs", side_effect=save_jobs),
                mock.patch.object(agent_routes.shorts_jobs, "_workers", {}),
            ):
                result = agent_routes.delete_failed_short_projects()

            self.assertEqual(result["deleted_projects"], 1)
            self.assertEqual(result["deleted_jobs"], 2)
            self.assertEqual(set(store), {completed_id})
            self.assertTrue((root / completed_id).exists())
            self.assertFalse((root / failed_root).exists())
            self.assertFalse((root / failed_revision).exists())

    def test_agent_history_routes_are_registered(self):
        app = FastAPI()
        agent_routes.install_routes(app)
        paths = {route.path for route in app.routes}
        self.assertIn("/api/shorts-jobs", paths)
        self.assertIn("/api/shorts-jobs/failed", paths)
        self.assertIn("/api/shorts-jobs/{job_id}", paths)
        self.assertIn("/api/shorts/jobs/{job_id}/scenes/{scene_id}/revise", paths)

    def test_agent_delete_route_returns_conflict_for_active_project(self):
        app = FastAPI()
        agent_routes.install_routes(app)
        client = TestClient(app)

        with mock.patch.object(
            agent_routes,
            "delete_short_project",
            side_effect=ValueError("active Shorts projects must be cancelled before deletion"),
        ):
            response = client.delete("/api/shorts-jobs/" + ("a" * 24))

        self.assertEqual(response.status_code, 409)

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

    def test_backend_delete_proxies_use_agent_endpoints(self):
        calls = []

        def requester(method, path, payload=None, timeout=10):
            calls.append((method, path, payload, timeout))
            return {"deleted": True}

        app = FastAPI()
        backend_routes.install_routes(app, requester)
        client = TestClient(app)
        job_id = "a" * 24

        response = client.delete(f"/api/mlx/shorts-jobs/{job_id}")
        self.assertEqual(response.status_code, 200)
        response = client.delete("/api/mlx/shorts-jobs/failed")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            calls,
            [
                ("DELETE", f"/api/shorts-jobs/{job_id}", None, 30),
                ("DELETE", "/api/shorts-jobs/failed", None, 30),
            ],
        )


if __name__ == "__main__":
    unittest.main()
