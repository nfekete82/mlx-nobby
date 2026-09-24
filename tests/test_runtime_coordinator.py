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
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            runtime_coordinator,
            "release_idle_image_runtime",
            return_value={"loaded": False},
        ):
            with runtime_coordinator.video_runtime(
                threading.Event(),
                chat_loaded=lambda: True,
                chat_command=commands.append,
                lock_path=Path(directory) / "runtime.lock",
            ):
                self.assertEqual(commands, ["stop"])

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
            ):
                pass

        sleep.assert_called_once_with(runtime_coordinator.POLL_INTERVAL)

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
