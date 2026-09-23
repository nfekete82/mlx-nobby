import json
import os
import subprocess
import tempfile
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

    def test_system_reboot_endpoint_launches_detached_rebuild_helper(self):
        with mock.patch.object(
            agent.subprocess,
            "Popen",
        ) as popen:
            response = self.client.post(
                "/api/system/reboot"
            )

        self.assertEqual(
            response.status_code,
            202,
            response.text,
        )

        self.assertEqual(
            response.json(),
            {"status": "accepted", "action": "reboot"},
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

    def test_shutdown_ai_endpoint_launches_detached_helper(self):
        with mock.patch.object(agent.subprocess, "Popen") as popen:
            response = self.client.post("/api/system/shutdown-ai")

        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(
            response.json(),
            {"status": "accepted", "action": "shutdown-ai"},
        )
        command = popen.call_args.args[0]
        self.assertTrue(str(command[0]).endswith("shutdown-ai.sh"), command)
        self.assertTrue(popen.call_args.kwargs.get("start_new_session"))


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

    def test_reboot_script_preserves_agent_rebuilds_and_restarts_services(self):
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
            '"$MLX_BIN" stop-ai',
            source,
        )

        self.assertNotIn('"$MLX_BIN" stop-all', source)

        self.assertIn(
            '"$DOCKER_BIN" compose',
            source,
        )

        self.assertIn("compose build mlx-web", source)

        self.assertIn(
            "mlx-web",
            source,
        )

        self.assertIn(
            '"$MLX_BIN" restart-all',
            source,
        )

        self.assertLess(source.index('"$MLX_BIN" stop-ai'), source.index('compose build mlx-web'))
        self.assertLess(source.index('compose build mlx-web'), source.index('compose up -d'))
        self.assertLess(
            source.index('compose up -d'),
            source.index('"$MLX_BIN" restart-all', source.index('compose up -d')),
        )

    def test_restart_script_reports_lifecycle_progress(self):
        text = Path(
            "scripts/restart-all.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "/api/system/lifecycle/progress",
            text,
        )
        self.assertIn(
            '"restart-services"',
            text,
        )
        self.assertIn(
            '"completed"',
            text,
        )

    def test_rebuild_script_reports_lifecycle_progress(self):
        text = Path(
            "scripts/rebuild-all.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "/api/system/lifecycle/progress",
            text,
        )
        self.assertIn(
            '"stop-ai"',
            text,
        )
        self.assertIn(
            '"build-web"',
            text,
        )
        self.assertIn(
            '"restart-services"',
            text,
        )
        self.assertIn(
            '"verify-services"',
            text,
        )
        self.assertIn(
            '"completed"',
            text,
        )

    def test_restart_all_keeps_healthy_agent_process(self):
        text = Path("scripts/mlx").read_text(encoding="utf-8")
        restart = text[text.index("restart_all()") : text.index("stop_ai()")]
        self.assertIn("mlx_service_ensure_running agent", restart)
        self.assertNotIn("mlx_service_restart agent", restart)

    def test_mlx_stop_ai_targets_only_owned_model_services(self):
        text = Path("scripts/mlx").read_text(encoding="utf-8")
        self.assertIn("stop_ai()", text)
        self.assertIn("video images speech embeddings router mlxserve server", text)
        self.assertIn('launchctl bootout "$domain/$label"', text)
        stop_ai = text[text.index("stop_ai()") : text.index("stop_all()")]
        self.assertNotIn("mlx_service_stop agent", stop_ai)

    def test_shutdown_ai_helper_reuses_mlx_stop_ai(self):
        text = Path("scripts/shutdown-ai.sh").read_text(encoding="utf-8")
        self.assertIn('"$MLX_BIN" stop-ai', text)
        self.assertIn('"action": "shutdown-ai"', text)


class RebootOrchestrationIntegrationTests(unittest.TestCase):

    def run_reboot(self, *, ports_ready=True):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = root / "calls.log"
            report_file = root / "reports.jsonl"
            mlx = root / "mlx"
            docker = root / "docker"
            port_check = root / "port-check"
            for path, body in (
                (mlx, '#!/bin/bash\necho "mlx $*" >> "$CALLS_LOG"\n'),
                (docker, '#!/bin/bash\necho "docker $*" >> "$CALLS_LOG"\n'),
                (port_check, '#!/bin/bash\necho "port $*" >> "$CALLS_LOG"\n' + ("exit 0\n" if ports_ready else "exit 1\n")),
            ):
                path.write_text(body, encoding="utf-8")
                path.chmod(0o755)

            env = os.environ | {
                "MLX_NOBBY_PROJECT_DIR": str(Path.cwd()),
                "MLX_BIN": str(mlx),
                "DOCKER_BIN": str(docker),
                "PORT_CHECK_BIN": str(port_check),
                "CALLS_LOG": str(calls),
                "MLX_NOBBY_REBOOT_LOG": str(root / "reboot.log"),
                "MLX_NOBBY_LIFECYCLE_REPORT_FILE": str(report_file),
                "MLX_NOBBY_REBOOT_PORTS": "8000 8010 8090",
                "MLX_NOBBY_SERVICE_WAIT_TIMEOUT": "1",
            }
            result = subprocess.run(
                ["scripts/rebuild-all.sh"], cwd=Path.cwd(), env=env,
                capture_output=True, text=True, timeout=15,
            )
            called = calls.read_text(encoding="utf-8").splitlines()
            reports = [
                json.loads(line)
                for line in report_file.read_text(encoding="utf-8").splitlines()
            ]

        return result, called, reports

    def test_real_helper_runs_full_sequence_before_completed(self):
        result, called, reports = self.run_reboot()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(called[:4], [
            "mlx stop-ai",
            "docker compose build mlx-web",
            "docker compose up -d --force-recreate mlx-web",
            "mlx restart-all",
        ])
        self.assertEqual(
            [line.split("-tiTCP:", 1)[1].split()[0] for line in called[4:]],
            ["8000", "8010", "8090"],
        )
        self.assertEqual(reports[-2]["phase"], "verify-services")
        self.assertLess(reports[-2]["current"], reports[-2]["total"])
        self.assertEqual(reports[-1]["state"], "completed")
        self.assertEqual(reports[-1]["current"], reports[-1]["total"])

    def test_real_helper_reports_port_timeout_as_failed(self):
        result, called, reports = self.run_reboot(ports_ready=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(reports[-1]["state"], "failed")
        self.assertEqual(reports[-1]["phase"], "verify-services")
        self.assertIn("Port 8000", reports[-1]["error"])
        self.assertEqual(called[-1], "mlx restart-all")


if __name__ == "__main__":
    unittest.main()
