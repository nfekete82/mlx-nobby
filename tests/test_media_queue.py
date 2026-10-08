import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent import media_queue


class MediaQueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.queue_directory = root / "media-queue"
        self.queue_file = self.queue_directory / "jobs.json"
        self.shorts_file = root / "shorts" / "jobs.json"
        self.patches = [
            mock.patch.object(media_queue, "QUEUE_DIRECTORY", self.queue_directory),
            mock.patch.object(media_queue, "QUEUE_FILE", self.queue_file),
            mock.patch.object(media_queue, "SHORTS_FILE", self.shorts_file),
            # The queue worker is a process-global daemon thread. A worker that
            # was started by another test can otherwise wake up while this test
            # owns the mocked queue and consume the same job concurrently with
            # a direct _dispatch_and_poll() call. Keep background selection idle
            # so these unit tests control dispatch deterministically.
            mock.patch.object(media_queue, "_next_job_id", return_value=None),
        ]
        for patcher in self.patches:
            patcher.start()
        with media_queue._jobs_lock:
            media_queue._jobs.clear()
            media_queue._loaded = False
        media_queue._wake.clear()

    def tearDown(self):
        with media_queue._jobs_lock:
            media_queue._jobs.clear()
            media_queue._loaded = False
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temporary.cleanup()

    def enqueue(self, kind="image", prompt="A queued image", run_id="run-1"):
        payload = {
            "operation": "generate" if kind == "image" else "t2v",
            "payload": {"prompt": prompt, "model": "auto"},
            "chat_id": "chat-1",
            "run_id": run_id,
            "chat_revision": 1,
        }
        with mock.patch.object(media_queue, "ensure_worker"):
            return media_queue.enqueue(kind, payload)

    def test_enqueue_is_persistent_and_returns_compatible_job_shape(self):
        job = self.enqueue()

        self.assertEqual(job["kind"], "image")
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["phase"], "queued")
        self.assertEqual(job["title"], "A queued image")
        self.assertTrue(job["cancellable"])
        self.assertNotIn("request", job)

        stored = json.loads(self.queue_file.read_text(encoding="utf-8"))
        self.assertIn(job["id"], stored)
        self.assertEqual(stored[job["id"]]["request"]["run_id"], "run-1")

    def test_public_job_hides_internal_dispatching_state(self):
        job = self.enqueue()

        with media_queue._jobs_lock:
            internal = media_queue._jobs[job["id"]]
            internal["status"] = "dispatching"
            internal["phase"] = "dispatching"
            media_queue._persist_locked()

        public = media_queue.get_job("image", job["id"])

        self.assertEqual(public["status"], "queued")
        self.assertEqual(public["phase"], "queued")
        self.assertTrue(public["cancellable"])
        with media_queue._jobs_lock:
            self.assertEqual(media_queue._jobs[job["id"]]["status"], "dispatching")
            self.assertEqual(media_queue._jobs[job["id"]]["phase"], "dispatching")

    def test_dispatch_mirrors_native_job_until_completion(self):
        job = self.enqueue(kind="video", prompt="Queued video")
        native_id = "a" * 24
        responses = [
            {
                "id": native_id,
                "status": "queued",
                "phase": "waiting_for_resources",
                "progress": 0.0,
            },
            {
                "id": native_id,
                "status": "generating",
                "phase": "denoising",
                "progress": 0.5,
            },
            {
                "id": native_id,
                "status": "completed",
                "phase": "completed",
                "progress": 1.0,
                "runtime_handoff": {
                    "duration_ms": 125.5,
                    "chat_released": False,
                    "speech_released": True,
                },
                "result": {"path": "/tmp/video.mp4"},
            },
        ]
        calls = []

        def requester(kind, method, path, payload=None, timeout=20):
            calls.append((kind, method, path))
            return responses.pop(0)

        with mock.patch.object(media_queue, "_service_request", side_effect=requester), \
             mock.patch.object(media_queue, "_wait"):
            media_queue._dispatch_and_poll(job["id"])

        completed = media_queue.get_job("video", job["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["progress"], 1.0)
        self.assertEqual(completed["native_job_id"], native_id)
        self.assertEqual(completed["result"]["path"], "/tmp/video.mp4")
        self.assertEqual(completed["runtime_handoff"]["duration_ms"], 125.5)
        self.assertTrue(completed["runtime_handoff"]["speech_released"])
        stored = json.loads(self.queue_file.read_text(encoding="utf-8"))
        self.assertEqual(stored[job["id"]]["runtime_handoff"], completed["runtime_handoff"])
        self.assertEqual(calls[0][:2], ("video", "POST"))
        self.assertEqual(calls[-1], ("video", "GET", f"/jobs/{native_id}"))

    def test_service_conflict_keeps_job_waiting_instead_of_failing(self):
        job = self.enqueue(kind="video")
        attempts = []

        def requester(*args, **kwargs):
            attempts.append(args)
            if len(attempts) == 1:
                raise media_queue.ServiceError(409, "busy")
            return {
                "id": "b" * 24,
                "status": "completed",
                "phase": "completed",
                "progress": 1.0,
                "result": {"path": "/tmp/result.mp4"},
            }

        with mock.patch.object(media_queue, "_service_request", side_effect=requester), \
             mock.patch.object(media_queue, "_wait"):
            media_queue._dispatch_and_poll(job["id"])

        completed = media_queue.get_job("video", job["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertGreaterEqual(completed["dispatch_attempts"], 2)

    def test_cancel_queued_job_never_dispatches_it(self):
        job = self.enqueue()
        cancelled = media_queue.cancel("image", job["id"])

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertFalse(cancelled["cancellable"])
        with mock.patch.object(media_queue, "_service_request") as request:
            media_queue._dispatch_and_poll(job["id"])
        request.assert_not_called()

    def test_snapshot_replaces_short_child_with_parent_and_positions_waiters(self):
        first = self.enqueue(kind="image", prompt="Standalone image")
        child = self.enqueue(kind="video", prompt="Short scene", run_id="short-run")

        self.shorts_file.parent.mkdir(parents=True, exist_ok=True)
        short_id = "c" * 24
        self.shorts_file.write_text(
            json.dumps({
                short_id: {
                    "id": short_id,
                    "run_id": "short-run",
                    "chat_id": "chat-1",
                    "status": "running",
                    "phase": "video",
                    "created_at": 1.0,
                    "started_at": 1.0,
                    "finished_at": None,
                    "current_scene": 0,
                    "active_video_job_id": child["id"],
                    "scene_results": [],
                    "project": {
                        "title": "Berlin 2040",
                        "scenes": [{"id": "s1"}, {"id": "s2"}],
                    },
                    "error": None,
                }
            }),
            encoding="utf-8",
        )

        with mock.patch.object(media_queue, "ensure_worker"), \
             mock.patch.object(
                 media_queue.runtime_coordinator,
                 "runtime_state_snapshot",
                 return_value={"active": None, "waiting": [], "waiting_count": 0},
             ):
            snapshot = media_queue.snapshot()

        ids = [item["id"] for item in snapshot["jobs"]]
        self.assertIn(first["id"], ids)
        self.assertIn(short_id, ids)
        self.assertNotIn(child["id"], ids)
        short = next(item for item in snapshot["jobs"] if item["id"] == short_id)
        self.assertEqual(short["kind"], "shorts")
        self.assertEqual(short["title"], "Berlin 2040")
        self.assertEqual(short["queue_status"], "waiting")
        self.assertIsInstance(short["queue_position"], int)


if __name__ == "__main__":
    unittest.main()
