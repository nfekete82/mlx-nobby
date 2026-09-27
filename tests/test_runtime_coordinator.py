import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import image_service
import runtime_coordinator


class RuntimeCoordinatorTests(unittest.TestCase):
    def test_idle_loaded_image_is_unloaded_before_video(self):
        calls = []
        health = [
            {"status": "ready", "active_generation": False, "loaded": True},
            {"status": "ready", "active_generation": False, "loaded": False},
        ]

        def requester(method, url, payload=None, timeout=10):
            calls.append((method, url))
            if method == "POST":
                return {"ok": True, "loaded": False}
            return health.pop(0)

        result = runtime_coordinator.release_idle_image_runtime(
            requester=requester
        )

        self.assertFalse(result["loaded"])
        self.assertEqual(
            [method for method, _url in calls],
            ["GET", "POST", "GET"],
        )

    def test_video_waits_for_active_image_without_unloading_it(self):
        calls = []
        health = [
            {"status": "busy", "active_generation": True, "loaded": True},
            {"status": "ready", "active_generation": False, "loaded": False},
        ]

        def requester(method, url, payload=None, timeout=10):
            calls.append((method, url))
            return health.pop(0)

        with mock.patch.object(runtime_coordinator.time, "sleep") as sleep:
            runtime_coordinator.release_idle_image_runtime(requester=requester)

        sleep.assert_called_once_with(runtime_coordinator.POLL_INTERVAL)
        self.assertEqual([method for method, _url in calls], ["GET", "GET"])

    def test_waiting_handoff_preserves_cancellation(self):
        cancel = threading.Event()

        def requester(method, url, payload=None, timeout=10):
            cancel.set()
            return {
                "status": "busy",
                "active_generation": True,
                "loaded": True,
            }

        with mock.patch.object(runtime_coordinator.time, "sleep"):
            with self.assertRaises(runtime_coordinator.CoordinationCancelled):
                runtime_coordinator.release_idle_image_runtime(
                    cancel,
                    requester=requester,
                )

    def test_video_stops_and_restores_previously_loaded_chat(self):
        commands = []
        memory = {
            "pressure": "normal",
            "headroom_gb": 12.0,
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            runtime_coordinator,
            "release_idle_image_runtime",
            return_value={"loaded": False},
        ), mock.patch.object(
            runtime_coordinator,
            "memory_budget_snapshot",
            return_value=memory,
        ):
            with runtime_coordinator.video_runtime(
                threading.Event(),
                chat_loaded=lambda: True,
                chat_command=commands.append,
                lock_path=Path(directory) / "runtime.lock",
            ) as preflight:
                self.assertEqual(commands, ["stop"])
                self.assertEqual(preflight["memory_before"], memory)
                self.assertTrue(preflight["chat_released"])
                self.assertFalse(preflight["memory_relief_needed"])

        self.assertEqual(commands, ["stop", "start"])

    def test_image_waits_for_active_video(self):
        health = [
            {"status": "busy", "active_generation": True},
            {"status": "ready", "active_generation": False},
        ]

        def requester(method, url, payload=None, timeout=10):
            self.assertEqual(method, "GET")
            return health.pop(0)

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            runtime_coordinator.time, "sleep"
        ) as sleep:
            with runtime_coordinator.image_runtime(
                threading.Event(),
                requester=requester,
                lock_path=Path(directory) / "runtime.lock",
                chat_loaded=lambda: False,
                memory_snapshot=lambda: {
                    "pressure": "normal",
                    "headroom_gb": 12.0,
                },
            ):
                pass

        sleep.assert_called_once_with(runtime_coordinator.POLL_INTERVAL)

    def test_memory_relief_needed_for_pressure_or_low_headroom(self):
        self.assertTrue(runtime_coordinator.memory_relief_needed({
            "pressure": "elevated",
            "headroom_gb": 20.0,
        }))
        self.assertTrue(runtime_coordinator.memory_relief_needed({
            "pressure": "critical",
            "headroom_gb": 20.0,
        }))
        self.assertTrue(runtime_coordinator.memory_relief_needed({
            "pressure": "normal",
            "headroom_gb": runtime_coordinator.MEDIA_MIN_HEADROOM_GB - 0.1,
        }))
        self.assertFalse(runtime_coordinator.memory_relief_needed({
            "pressure": "normal",
            "headroom_gb": runtime_coordinator.MEDIA_MIN_HEADROOM_GB + 2,
        }))
        self.assertFalse(runtime_coordinator.memory_relief_needed({
            "pressure": "unknown",
            "headroom_gb": None,
        }))

    def test_image_releases_chat_when_memory_pressure_is_elevated(self):
        commands = []

        def requester(method, url, payload=None, timeout=10):
            self.assertEqual(method, "GET")
            self.assertTrue(url.endswith("/health"))
            return {"status": "ready", "active_generation": False}

        with tempfile.TemporaryDirectory() as directory:
            with runtime_coordinator.image_runtime(
                threading.Event(),
                requester=requester,
                lock_path=Path(directory) / "runtime.lock",
                chat_loaded=lambda: True,
                chat_command=commands.append,
                memory_snapshot=lambda: {
                    "pressure": "elevated",
                    "headroom_gb": 1.5,
                },
            ) as preflight:
                self.assertEqual(commands, ["stop"])
                self.assertTrue(preflight["memory_relief_needed"])
                self.assertTrue(preflight["chat_released"])

        self.assertEqual(commands, ["stop", "start"])

    def test_image_keeps_chat_loaded_with_healthy_memory(self):
        commands = []
        chat_probe = mock.Mock(return_value=True)

        def requester(method, url, payload=None, timeout=10):
            return {"status": "ready", "active_generation": False}

        with tempfile.TemporaryDirectory() as directory:
            with runtime_coordinator.image_runtime(
                threading.Event(),
                requester=requester,
                lock_path=Path(directory) / "runtime.lock",
                chat_loaded=chat_probe,
                chat_command=commands.append,
                memory_snapshot=lambda: {
                    "pressure": "normal",
                    "headroom_gb": 10.0,
                },
            ) as preflight:
                self.assertFalse(preflight["memory_relief_needed"])
                self.assertFalse(preflight["chat_released"])

        chat_probe.assert_not_called()
        self.assertEqual(commands, [])

    def test_consecutive_image_jobs_keep_mlxserve_model_warm(self):
        model = {
            "id": "image-model",
            "repository": "org/image-model",
            "provider": "mlxserve",
            "model_family": "qwen-image21",
            "default_steps": 4,
            "default_guidance": 1,
            "quantization": "4-bit",
            "loras": [],
        }

        with tempfile.TemporaryDirectory() as directory:
            old_output = image_service.OUTPUT
            image_service.OUTPUT = Path(directory)
            try:
                with mock.patch.object(
                    image_service, "_generation_model", return_value=model
                ), mock.patch.object(
                    image_service, "_chat_server_loaded", return_value=False
                ), mock.patch.object(
                    image_service, "run_provider"
                ), mock.patch.object(
                    image_service, "_unload_mlxserve_model"
                ) as unload:
                    for prompt in ("First warm image", "Second warm image"):
                        image_service._generate_result(
                            image_service.Generate(prompt=prompt)
                        )
            finally:
                image_service.OUTPUT = old_output

        unload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
