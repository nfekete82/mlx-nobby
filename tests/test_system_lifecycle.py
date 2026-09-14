import subprocess
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from agent import app as agent


class SystemLifecycleTests(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(
            agent.app,
            base_url="http://localhost",
        )

    def test_restart_all_endpoint_launches_detached_helper(self):
        with mock.patch.object(
            agent.subprocess,
            "Popen",
        ) as popen:
            response = self.client.post(
                "/api/system/restart-all"
            )

        self.assertEqual(
            response.status_code,
            202,
            response.text,
        )

        self.assertEqual(
            response.json()["status"],
            "accepted",
        )

        popen.assert_called_once()

        args, kwargs = popen.call_args

        command = args[0]

        self.assertTrue(
            str(command[0]).endswith(
                "restart-all.sh"
            ),
            command,
        )

        self.assertTrue(
            kwargs.get("start_new_session"),
            "restart helper must be detached from agent process",
        )

        self.assertEqual(
            kwargs.get("stdin"),
            subprocess.DEVNULL,
        )

    def test_rebuild_all_endpoint_launches_detached_helper(self):
        with mock.patch.object(
            agent.subprocess,
            "Popen",
        ) as popen:
            response = self.client.post(
                "/api/system/rebuild-all"
            )

        self.assertEqual(
            response.status_code,
            202,
            response.text,
        )

        self.assertEqual(
            response.json()["status"],
            "accepted",
        )

        popen.assert_called_once()

        args, kwargs = popen.call_args

        command = args[0]

        self.assertTrue(
            str(command[0]).endswith(
                "rebuild-all.sh"
            ),
            command,
        )

        self.assertTrue(
            kwargs.get("start_new_session"),
            "rebuild helper must survive agent restart",
        )

        self.assertEqual(
            kwargs.get("stdin"),
            subprocess.DEVNULL,
        )


class LifecycleScriptContractTests(unittest.TestCase):

    def test_restart_script_uses_existing_mlx_restart_all(self):
        path = Path(
            "scripts/restart-all.sh"
        )

        self.assertTrue(
            path.is_file(),
            "scripts/restart-all.sh must exist",
        )

        source = path.read_text(
            encoding="utf-8",
        )

        self.assertIn(
            '"$MLX_BIN" restart-all',
            source,
        )

        self.assertIn(
            "$HOME/bin/mlx",
            source,
        )

    def test_rebuild_script_rebuilds_web_then_restarts_services(self):
        path = Path(
            "scripts/rebuild-all.sh"
        )

        self.assertTrue(
            path.is_file(),
            "scripts/rebuild-all.sh must exist",
        )

        source = path.read_text(
            encoding="utf-8",
        )

        self.assertIn(
            '"$DOCKER_BIN" compose',
            source,
        )

        self.assertIn(
            "--build",
            source,
        )

        self.assertIn(
            "mlx-web",
            source,
        )

        self.assertIn(
            '"$MLX_BIN" restart-all',
            source,
        )


if __name__ == "__main__":
    unittest.main()
