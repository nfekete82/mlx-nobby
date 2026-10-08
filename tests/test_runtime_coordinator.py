import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import image_service
import runtime_coordinator


class RuntimeCoordinatorTests(unittest.TestCase):
    def test_configured_hard_limit_cannot_exceed_90_percent(self):
        for configured, expected in [("99", 90.0), ("90", 90.0), ("85", 85.0),
                                     ("invalid", 90.0), ("inf", 90.0),
                                     ("nan", 50.0)]:
            with self.subTest(configured=configured):
                result = subprocess.run(
                    [sys.executable, "-c", (
                        "import runtime_coordinator as r; "
                        "assert r.memory_hard_limit_reached({'free_percent': 10}); "
                        "assert r.projected_memory_hard_limit_reached("
                        "{'total_gb': 48, 'used_estimate_gb': 40}, 4); "
                        "print(r.HARD_MEMORY_USED_PERCENT)"
                    )],
                    cwd=Path(runtime_coordinator.__file__).parent,
                    env=dict(os.environ, MLX_RUNTIME_HARD_USED_PERCENT=configured),
                    capture_output=True, text=True, check=True, timeout=10,
                )
                self.assertEqual(float(result.stdout), expected)

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

    def test_video_stops_and_restores_previously_loaded_chat_when_headroom_is_low(self):
        commands = []
        memory_before = {
            "pressure": "normal",
            "headroom_gb": 12.0,
        }
        memory_safe = {
            "pressure": "normal",
            "headroom_gb": 20.0,
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            runtime_coordinator,
            "release_idle_image_runtime",
            return_value={"loaded": False},
        ), mock.patch.object(
            runtime_coordinator,
            "memory_budget_snapshot",
            side_effect=[memory_before, memory_safe, memory_safe],
        ), mock.patch.object(
            runtime_coordinator,
            "release_idle_speech_runtime",
            return_value={"released": False},
        ), mock.patch.object(
            runtime_coordinator,
            "release_idle_musetalk_runtime",
            return_value={"released": False},
        ):
            with runtime_coordinator.video_runtime(
                threading.Event(),
                chat_loaded=lambda: True,
                chat_command=commands.append,
                lock_path=Path(directory) / "runtime.lock",
            ) as preflight:
                self.assertEqual(commands, ["stop"])
                self.assertEqual(preflight["memory_before"], memory_before)
                self.assertTrue(preflight["chat_released"])
                self.assertTrue(preflight["memory_relief_needed"])
                self.assertEqual(
                    preflight["required_headroom_gb"],
                    runtime_coordinator.VIDEO_MIN_HEADROOM_GB,
                )

        self.assertEqual(commands, ["stop", "start"])

    def test_video_keeps_chat_warm_when_memory_headroom_is_healthy(self):
        commands = []
        chat_probe = mock.Mock(return_value=True)
        memory = {
            "pressure": "normal",
            "headroom_gb": runtime_coordinator.VIDEO_MIN_HEADROOM_GB + 4.0,
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
                chat_loaded=chat_probe,
                chat_command=commands.append,
                lock_path=Path(directory) / "runtime.lock",
            ) as preflight:
                self.assertFalse(preflight["memory_relief_needed"])
                self.assertFalse(preflight["chat_released"])
                timings = preflight["handoff_timings_ms"]
                self.assertGreaterEqual(timings["total"], 0)
                self.assertGreaterEqual(timings["lease_wait"], 0)
                self.assertGreaterEqual(timings["image_release"], 0)
                self.assertNotIn("chat_stop", timings)
                self.assertNotIn("speech_release", timings)
                self.assertNotIn("musetalk_release", timings)

        chat_probe.assert_not_called()
        self.assertEqual(commands, [])


    def test_video_reclaims_idle_speech_without_stopping_chat(self):
        before = {
            "pressure": "normal",
            "headroom_gb": 7.0,
            "used_estimate_gb": 35.0,
            "total_gb": 48.0,
        }
        after_speech = {
            "pressure": "normal",
            "headroom_gb": 23.0,
            "used_estimate_gb": 19.0,
            "total_gb": 48.0,
        }
        chat_probe = mock.Mock(return_value=True)
        commands = []
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            runtime_coordinator,
            "release_idle_image_runtime",
            return_value={"loaded": False},
        ), mock.patch.object(
            runtime_coordinator,
            "release_idle_speech_runtime",
            return_value={"released": True},
        ) as speech_release, mock.patch.object(
            runtime_coordinator,
            "release_idle_musetalk_runtime",
        ) as musetalk_release, mock.patch.object(
            runtime_coordinator,
            "memory_budget_snapshot",
            side_effect=[before, after_speech],
        ):
            with runtime_coordinator.video_runtime(
                threading.Event(),
                chat_loaded=chat_probe,
                chat_command=commands.append,
                lock_path=Path(directory) / "runtime.lock",
            ) as preflight:
                self.assertTrue(preflight["speech_released"])
                self.assertFalse(preflight["musetalk_released"])
                self.assertFalse(preflight["chat_released"])
                self.assertEqual(preflight["memory_admission"], after_speech)
                self.assertFalse(preflight["hard_limit_reached"])

        speech_release.assert_called_once()
        musetalk_release.assert_not_called()
        chat_probe.assert_not_called()
        self.assertEqual(commands, [])

    def test_video_reclaims_idle_musetalk_before_stopping_chat(self):
        before = {
            "pressure": "normal",
            "headroom_gb": 7.0,
            "used_estimate_gb": 35.0,
            "total_gb": 48.0,
        }
        after_musetalk = {
            "pressure": "normal",
            "headroom_gb": 24.0,
            "used_estimate_gb": 18.0,
            "total_gb": 48.0,
        }
        chat_probe = mock.Mock(return_value=True)
        commands = []
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            runtime_coordinator,
            "release_idle_image_runtime",
            return_value={"loaded": False},
        ), mock.patch.object(
            runtime_coordinator,
            "release_idle_speech_runtime",
            return_value={"released": False},
        ), mock.patch.object(
            runtime_coordinator,
            "release_idle_musetalk_runtime",
            return_value={"released": True},
        ) as musetalk_release, mock.patch.object(
            runtime_coordinator,
            "memory_budget_snapshot",
            side_effect=[before, after_musetalk],
        ):
            with runtime_coordinator.video_runtime(
                threading.Event(),
                chat_loaded=chat_probe,
                chat_command=commands.append,
                lock_path=Path(directory) / "runtime.lock",
            ) as preflight:
                self.assertFalse(preflight["speech_released"])
                self.assertTrue(preflight["musetalk_released"])
                self.assertFalse(preflight["chat_released"])
                self.assertEqual(preflight["memory_admission"], after_musetalk)

        musetalk_release.assert_called_once()
        chat_probe.assert_not_called()
        self.assertEqual(commands, [])

    def test_video_stops_chat_if_idle_model_reclaim_is_insufficient(self):
        snapshots = [
            {"pressure": "normal", "headroom_gb": 7.0,
             "used_estimate_gb": 35.0, "total_gb": 48.0},
            {"pressure": "normal", "headroom_gb": 9.0,
             "used_estimate_gb": 32.0, "total_gb": 48.0},
            {"pressure": "normal", "headroom_gb": 10.0,
             "used_estimate_gb": 31.0, "total_gb": 48.0},
            {"pressure": "normal", "headroom_gb": 23.0,
             "used_estimate_gb": 18.0, "total_gb": 48.0},
            {"pressure": "normal", "headroom_gb": 24.0,
             "used_estimate_gb": 17.0, "total_gb": 48.0},
        ]
        commands = []
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            runtime_coordinator,
            "release_idle_image_runtime",
            return_value={"loaded": False},
        ), mock.patch.object(
            runtime_coordinator,
            "release_idle_speech_runtime",
            return_value={"released": True},
        ), mock.patch.object(
            runtime_coordinator,
            "release_idle_musetalk_runtime",
            return_value={"released": True},
        ), mock.patch.object(
            runtime_coordinator,
            "memory_budget_snapshot",
            side_effect=snapshots,
        ):
            with runtime_coordinator.video_runtime(
                threading.Event(),
                chat_loaded=lambda: True,
                chat_command=commands.append,
                lock_path=Path(directory) / "runtime.lock",
            ) as preflight:
                self.assertTrue(preflight["speech_released"])
                self.assertTrue(preflight["musetalk_released"])
                self.assertTrue(preflight["chat_released"])
                timings = preflight["handoff_timings_ms"]
                self.assertGreaterEqual(timings["speech_release"], 0)
                self.assertGreaterEqual(timings["musetalk_release"], 0)
                self.assertGreaterEqual(timings["chat_stop"], 0)
                self.assertEqual(preflight["memory_admission"], snapshots[3])
                self.assertFalse(preflight["hard_limit_reached"])

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


    def test_memory_hard_limit_reached_at_90_percent_used(self):
        self.assertTrue(runtime_coordinator.memory_hard_limit_reached({
            "pressure": "elevated",
            "free_percent": 10.0,
        }))
        self.assertTrue(runtime_coordinator.memory_hard_limit_reached({
            "pressure": "normal",
            "used_estimate_gb": 43.2,
            "total_gb": 48.0,
        }))
        self.assertFalse(runtime_coordinator.memory_hard_limit_reached({
            "pressure": "normal",
            "free_percent": 10.1,
        }))


    def test_projected_model_load_reserve_blocks_before_90_percent(self):
        snapshot = {
            "pressure": "normal",
            "used_estimate_gb": 40.0,
            "total_gb": 48.0,
            "free_percent": 16.67,
        }
        self.assertTrue(
            runtime_coordinator.projected_memory_hard_limit_reached(
                snapshot,
                reserve_gb=4.0,
            )
        )
        self.assertFalse(
            runtime_coordinator.projected_memory_hard_limit_reached(
                snapshot,
                reserve_gb=2.0,
            )
        )

    def test_global_model_load_guard_uses_workload_reserve(self):
        snapshot = {
            "pressure": "normal",
            "used_estimate_gb": 40.0,
            "total_gb": 48.0,
            "free_percent": 16.67,
        }
        with self.assertRaisesRegex(RuntimeError, "Embedding|embedding|90%"):
            runtime_coordinator.ensure_model_load_allowed(
                "embedding",
                snapshot=snapshot,
            )

        admitted = runtime_coordinator.ensure_model_load_allowed(
            "vision-classifier",
            snapshot={
                "pressure": "normal",
                "used_estimate_gb": 20.0,
                "total_gb": 48.0,
                "free_percent": 58.33,
            },
        )
        self.assertEqual(admitted["used_estimate_gb"], 20.0)

    def test_image_blocks_new_runtime_when_ram_hard_limit_is_reached(self):
        def requester(method, url, payload=None, timeout=10):
            return {"status": "ready", "active_generation": False}

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "90%"):
                with runtime_coordinator.image_runtime(
                    threading.Event(),
                    requester=requester,
                    lock_path=Path(directory) / "runtime.lock",
                    chat_loaded=lambda: False,
                    memory_snapshot=lambda: {
                        "pressure": "elevated",
                        "free_percent": 9.0,
                        "headroom_gb": 0.0,
                    },
                ):
                    self.fail("hard RAM limit must block image runtime")

    def test_prepare_chat_runtime_allows_already_loaded_model_at_high_ram(self):
        def requester(method, url, payload=None, timeout=10):
            return {
                "status": "ready",
                "active_generation": False,
                "loaded": False,
            }

        memory = {
            "pressure": "elevated",
            "free_percent": 9.0,
            "headroom_gb": 0.0,
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            runtime_coordinator,
            "memory_budget_snapshot",
            return_value=memory,
        ):
            result = runtime_coordinator.prepare_chat_runtime(
                requester=requester,
                lock_path=Path(directory) / "runtime.lock",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["memory"], memory)

    def test_image_releases_idle_speech_before_stopping_chat(self):
        calls = []
        snapshots = iter([
            {
                "pressure": "normal",
                "used_estimate_gb": 35.0,
                "total_gb": 48.0,
                "free_percent": 27.08,
                "headroom_gb": 7.0,
            },
            {
                "pressure": "normal",
                "used_estimate_gb": 20.0,
                "total_gb": 48.0,
                "free_percent": 58.33,
                "headroom_gb": 22.0,
            },
        ])

        speech_health_calls = 0

        def requester(method, url, payload=None, timeout=10):
            nonlocal speech_health_calls
            calls.append((method, url))
            if url.startswith(runtime_coordinator.VIDEO_URL):
                return {"status": "ready", "active_generation": False}
            if method == "POST" and url == runtime_coordinator.SPEECH_URL + "/unload":
                return {"ok": True}
            if url == runtime_coordinator.SPEECH_URL + "/health":
                speech_health_calls += 1
                return {
                    "status": "ok",
                    "active_generation": False,
                    "loaded": False,
                    "tts_loaded": speech_health_calls == 1,
                    "tts_clone_loaded": False,
                }
            raise AssertionError(url)

        chat_probe = mock.Mock(return_value=True)
        commands = []
        with tempfile.TemporaryDirectory() as directory:
            with runtime_coordinator.image_runtime(
                threading.Event(),
                requester=requester,
                lock_path=Path(directory) / "runtime.lock",
                chat_loaded=chat_probe,
                chat_command=commands.append,
                memory_snapshot=lambda: next(snapshots),
            ) as preflight:
                self.assertTrue(preflight["speech_released"])
                self.assertFalse(preflight["chat_released"])
                self.assertEqual(
                    preflight["memory_admission"]["used_estimate_gb"],
                    20.0,
                )

        self.assertIn(
            ("POST", runtime_coordinator.SPEECH_URL + "/unload"),
            calls,
        )
        chat_probe.assert_not_called()
        self.assertEqual(commands, [])

    def test_image_releases_chat_when_projected_load_would_cross_limit(self):
        commands = []
        memory = iter([
            {
                "pressure": "normal",
                "used_estimate_gb": 35.0,
                "total_gb": 48.0,
                "free_percent": 27.08,
                "headroom_gb": 7.0,
            },
            {
                "pressure": "normal",
                "used_estimate_gb": 15.0,
                "total_gb": 48.0,
                "free_percent": 68.75,
                "headroom_gb": 27.0,
            },
            {
                "pressure": "normal",
                "used_estimate_gb": 15.0,
                "total_gb": 48.0,
                "free_percent": 68.75,
                "headroom_gb": 27.0,
            },
        ])

        def requester(method, url, payload=None, timeout=10):
            return {"status": "ready", "active_generation": False}

        with tempfile.TemporaryDirectory() as directory:
            with runtime_coordinator.image_runtime(
                threading.Event(),
                requester=requester,
                lock_path=Path(directory) / "runtime.lock",
                chat_loaded=lambda: True,
                chat_command=commands.append,
                memory_snapshot=lambda: next(memory),
            ) as preflight:
                self.assertTrue(preflight["memory_relief_needed"])
                self.assertTrue(preflight["chat_released"])
                self.assertFalse(preflight["hard_limit_reached"])

        self.assertEqual(commands, ["stop", "start"])

    def test_image_releases_chat_when_memory_pressure_is_elevated(self):
        commands = []
        memory = iter([
            {"pressure": "elevated", "headroom_gb": 1.5},
            {"pressure": "normal", "headroom_gb": 9.0},
            {"pressure": "normal", "headroom_gb": 9.0},
        ])

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
                memory_snapshot=lambda: next(memory),
            ) as preflight:
                self.assertEqual(commands, ["stop"])
                self.assertTrue(preflight["memory_relief_needed"])
                self.assertTrue(preflight["chat_released"])

        self.assertEqual(commands, ["stop", "start"])
        self.assertFalse(preflight["chat_restore_skipped"])
        self.assertEqual(preflight["memory_after"]["pressure"], "normal")

    def test_image_skips_chat_restore_when_memory_stays_unsafe(self):
        commands = []
        memory = iter([
            {"pressure": "elevated", "headroom_gb": 1.5},
            {"pressure": "normal", "headroom_gb": 9.0},
            {"pressure": "critical", "headroom_gb": 0.5},
        ])

        def requester(method, url, payload=None, timeout=10):
            return {"status": "ready", "active_generation": False}

        with tempfile.TemporaryDirectory() as directory:
            with runtime_coordinator.image_runtime(
                threading.Event(),
                requester=requester,
                lock_path=Path(directory) / "runtime.lock",
                chat_loaded=lambda: True,
                chat_command=commands.append,
                memory_snapshot=lambda: next(memory),
            ) as preflight:
                self.assertEqual(commands, ["stop"])

        self.assertEqual(commands, ["stop"])
        self.assertTrue(preflight["chat_restore_skipped"])
        self.assertEqual(preflight["memory_after"]["pressure"], "critical")

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

    def test_consecutive_mlxserve_image_jobs_unload_after_each_run(self):
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
                    image_service.runtime_coordinator,
                    "ensure_model_load_allowed",
                    return_value={},
                ), mock.patch.object(
                    image_service, "_unload_mlxserve_model_and_wait"
                ) as unload:
                    for prompt in ("First image", "Second image"):
                        image_service._generate_result(
                            image_service.Generate(prompt=prompt)
                        )
            finally:
                image_service.OUTPUT = old_output

        self.assertEqual(unload.call_count, 2)


if __name__ == "__main__":
    unittest.main()


def test_image_releases_idle_musetalk_before_stopping_chat():
    calls = []
    snapshots = iter([
        {
            "pressure": "normal",
            "used_estimate_gb": 35.0,
            "total_gb": 48.0,
            "free_percent": 27.08,
            "headroom_gb": 7.0,
        },
        {
            "pressure": "normal",
            "used_estimate_gb": 19.0,
            "total_gb": 48.0,
            "free_percent": 60.42,
            "headroom_gb": 23.0,
        },
    ])
    musetalk_health_calls = 0

    def requester(method, url, payload=None, timeout=10):
        nonlocal musetalk_health_calls
        calls.append((method, url))
        if url.startswith(runtime_coordinator.VIDEO_URL):
            return {"status": "ready", "active_generation": False}
        if url == runtime_coordinator.SPEECH_URL + "/health":
            return {
                "status": "ok",
                "active_generation": False,
                "loaded": False,
                "tts_loaded": False,
                "tts_clone_loaded": False,
            }
        if url == runtime_coordinator.MUSETALK_URL + "/health":
            musetalk_health_calls += 1
            return {
                "ok": True,
                "active_generation": False,
                "loaded": musetalk_health_calls == 1,
            }
        if method == "POST" and url == runtime_coordinator.MUSETALK_URL + "/unload":
            return {"ok": True, "loaded": False}
        raise AssertionError(url)

    commands = []
    with tempfile.TemporaryDirectory() as directory:
        with runtime_coordinator.image_runtime(
            threading.Event(),
            requester=requester,
            lock_path=Path(directory) / "runtime.lock",
            chat_loaded=mock.Mock(return_value=True),
            chat_command=commands.append,
            memory_snapshot=lambda: next(snapshots),
        ) as preflight:
            assert preflight["musetalk_released"] is True
            assert preflight["chat_released"] is False
            assert preflight["memory_admission"]["used_estimate_gb"] == 19.0

    assert ("POST", runtime_coordinator.MUSETALK_URL + "/unload") in calls
    assert commands == []
