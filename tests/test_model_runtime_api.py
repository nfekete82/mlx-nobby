import tempfile
import json
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent import app as agent_app


class BusyLock:
    def acquire(self, blocking=True):
        return False

    def release(self):
        raise AssertionError("Busy lock must not be released")


class ModelRuntimeApiTests(unittest.TestCase):
    def test_model_input_compatibility_and_rejection_before_manager(self):
        cases = json.loads((Path(__file__).parent / 'fixtures/model_validation.json').read_text())
        cases.append({'alias': 'a' * 97, 'repo': 'owner/model', 'valid': True})
        client = TestClient(agent_app.app, base_url='http://localhost')
        for case in cases:
            with self.subTest(case=case), mock.patch.object(agent_app, 'load_models', return_value=[]), \
                    mock.patch.object(agent_app.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='', stderr='')) as manager, \
                    mock.patch.object(agent_app, 'create_background_job', return_value={'id': 'test'}):
                response = client.post('/api/models/add', json={'alias': case['alias'], 'repo': case['repo']})
                self.assertEqual(response.status_code, 200 if case['valid'] else 400, response.text)
                if case['valid']:
                    args = manager.call_args.args[0]
                    self.assertEqual(args[3], case['alias'].strip())
                    self.assertEqual(args[4], str(Path(case['repo'].strip()).expanduser()) if case['repo'].strip().startswith(('~/', '/')) else case['repo'].strip())
                else:
                    manager.assert_not_called()

    def test_existing_local_reference_can_switch_but_unsafe_reference_cannot(self):
        for repo, valid in [('~/Models/Qwen3.8-27B/6-bit', True), ('/Models/a$variable', False)]:
            with self.subTest(repo=repo), mock.patch.object(agent_app, 'load_models', return_value=[{'alias': '_local', 'repo': repo}]), \
                    mock.patch.object(agent_app.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='', stderr='')) as manager, \
                    mock.patch.object(agent_app, 'wait_for_model_runtime', return_value={'ok': True}):
                if valid:
                    self.assertTrue(agent_app.switch_model_runtime('_local')['ok'])
                    self.assertEqual(manager.call_args.args[0][-1], '_local')
                else:
                    with self.assertRaises(HTTPException):
                        agent_app.switch_model_runtime('_local')
                    manager.assert_not_called()

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
