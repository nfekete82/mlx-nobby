import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from agent import app as agent_app


class BusyLock:
    def acquire(self, blocking=True):
        return False

    def release(self):
        raise AssertionError("Busy lock must not be released")


class ModelRuntimeApiTests(unittest.TestCase):
    def test_cache_summary_uses_real_sizes_and_exposes_path(self):
        items = [
            {
                "repo": "owner/one",
                "alias": "one",
                "path": "/cache/models--owner--one",
                "size_bytes": 1024,
                "size": "1.0 KB",
                "complete": True,
                "incomplete_files": 0,
                "incomplete_bytes": 0,
                "incomplete_size": "0.0 B",
            },
            {
                "repo": "owner/two",
                "alias": None,
                "path": "/cache/models--owner--two",
                "size_bytes": 2048,
                "size": "2.0 KB",
                "complete": False,
                "incomplete_files": 1,
                "incomplete_bytes": 10,
                "incomplete_size": "10.0 B",
            },
        ]
        with mock.patch.object(agent_app, "load_cache", return_value=items), mock.patch.object(
            agent_app,
            "load_config",
            return_value={"MODEL": "owner/one"},
        ):
            result = agent_app.cache()

        self.assertEqual(result["total_size_bytes"], 3072)
        self.assertEqual(result["total_size"], "3.0 KB")
        self.assertTrue(result["path"].endswith(".cache/huggingface/hub"))
        self.assertTrue(result["models"][0]["active"])
        self.assertEqual(result["incomplete"], 1)

    def test_local_model_add_does_not_start_download(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "local-model"
            model_path.mkdir()
            request = agent_app.AddModelRequest(alias="local", repo=str(model_path))
            process = mock.Mock(returncode=0, stdout="added", stderr="")

            with mock.patch.object(agent_app, "load_models", return_value=[]), mock.patch.object(
                agent_app.subprocess,
                "run",
                return_value=process,
            ), mock.patch.object(agent_app, "create_background_job") as download:
                result = agent_app.add_model(request)

        self.assertIsNone(result["job"])
        download.assert_not_called()

    def test_remote_model_add_keeps_background_download(self):
        request = agent_app.AddModelRequest(alias="remote", repo="owner/model")
        process = mock.Mock(returncode=0, stdout="added", stderr="")
        job = {"id": "job-1", "status": "queued"}

        with mock.patch.object(agent_app, "load_models", return_value=[]), mock.patch.object(
            agent_app.subprocess,
            "run",
            return_value=process,
        ), mock.patch.object(agent_app, "create_background_job", return_value=job) as download:
            result = agent_app.add_model(request)

        self.assertEqual(result["job"], job)
        download.assert_called_once_with("download", "remote")

    def test_runtime_mutations_reject_concurrent_action(self):
        with mock.patch.object(agent_app, "MODEL_RUNTIME_LOCK", BusyLock()):
            for action in (
                lambda: agent_app.server_command("restart"),
                lambda: agent_app.model_command("other"),
                lambda: agent_app.thinking_command("on"),
            ):
                with self.assertRaises(HTTPException) as context:
                    action()
                self.assertEqual(context.exception.status_code, 409)
                self.assertIn("Runtime-Aktion", context.exception.detail)


if __name__ == "__main__":
    unittest.main()
