"""Pure timing acceptance; no model loads, URLs, or private histories."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import image_service
import runtime_coordinator as rc
from agent import memory_model_coordination as ctl
from agent import memory_model_supervisor as sup


class ImageRuntimeProfilingTests(unittest.TestCase):
    def setUp(self):
        self.safe = {
            "total_gb": 48.0,
            "free_percent": 80.0,
            "used_estimate_gb": 9.6,
            "headroom_gb": 30.0,
            "pressure": "normal",
        }

    def test_image_handoff_records_real_stages_and_restore(self):
        commands = []
        with (mock.patch.object(rc, "runtime_lease"),
              mock.patch.object(rc, "wait_for_idle",
                                return_value={"loaded": False}),
              mock.patch.object(rc, "release_idle_speech_runtime",
                                return_value={"released": False}),
              mock.patch.object(rc, "release_idle_musetalk_runtime",
                                return_value={"released": False})):
            with rc.image_runtime(
                None, requester=mock.Mock(),
                chat_loaded=lambda: True,
                chat_command=commands.append,
                memory_snapshot=lambda: dict(self.safe),
                exclusive_models=True,
            ) as preflight:
                stages = preflight["handoff_timings_ms"]
                self.assertIn("lease_wait", stages)
                self.assertIn("video_wait", stages)
                self.assertIn("speech_release", stages)
                self.assertIn("musetalk_release", stages)
                self.assertIn("chat_stop", stages)
                self.assertIn("total", stages)
                self.assertNotIn("chat_restore", stages)
                self.assertTrue(preflight["chat_released"])
            self.assertIn("chat_restore", preflight["handoff_timings_ms"])
        self.assertEqual(commands, ["stop", "start"])
        for value in preflight["handoff_timings_ms"].values():
            self.assertGreaterEqual(value, 0.0)

    def test_no_release_when_headroom_is_enough_and_not_exclusive(self):
        with (mock.patch.object(rc, "runtime_lease"),
              mock.patch.object(rc, "wait_for_idle",
                                return_value={"loaded": False}),
              mock.patch.object(rc, "release_idle_speech_runtime") as speech,
              mock.patch.object(rc, "release_idle_musetalk_runtime") as muse):
            with rc.image_runtime(
                None, requester=mock.Mock(),
                chat_loaded=lambda: True,
                chat_command=mock.Mock(),
                memory_snapshot=lambda: dict(self.safe),
            ) as preflight:
                self.assertFalse(preflight["chat_released"])
                self.assertNotIn("chat_stop", preflight["handoff_timings_ms"])
            speech.assert_not_called()
            muse.assert_not_called()

    def test_persisted_image_metrics_are_bounded_and_private(self):
        source = {
            "handoff_timings_ms": {
                "lease_wait": 16.2, "video_wait": 0,
                "chat_restore": 400.51,
                "evil": "/Users/private/photo",
                "chat_stop": float("nan"),
                "total": 500.2,
            },
            "speech_released": True, "chat_released": True,
            "prompt": "PRIVATE IMAGE PROMPT",
        }
        result = image_service._image_handoff_measurement(source)
        self.assertEqual(result["version"], 4)
        self.assertEqual(result["duration_ms"], 500.2)
        self.assertEqual(result["timings_ms"]["chat_restore"], 400.51)
        self.assertNotIn("chat_stop", result["timings_ms"])
        self.assertNotIn("evil", result["timings_ms"])
        self.assertTrue(result["chat_released"])
        self.assertNotIn("/Users/private", json.dumps(result))
        self.assertNotIn("PRIVATE IMAGE PROMPT", json.dumps(result))
        self.assertIsNone(image_service._image_handoff_measurement(None))


class SupervisorTimingTests(unittest.TestCase):
    def test_bounded_samples_and_percentiles(self):
        manager = sup.Supervisor()
        for value in range(50):
            manager.record("model_api_ready_ms", value * 10)
        manager.record("model_api_ready_ms", float("nan"))
        manager.record("model_api_ready_ms", -1)
        manager.record("invalid", 22)
        stats = manager.performance()
        self.assertEqual(stats["model_api_ready_ms"]["count"], 32)
        self.assertEqual(stats["model_api_ready_ms"]["latest"], 490)
        self.assertEqual(stats["model_api_ready_ms"]["p50"], 335)
        self.assertEqual(stats["model_unload_ms"]["count"], 0)

    def test_api_ready_and_resume_recorded_once_per_start(self):
        manager = sup.Supervisor()
        child = mock.Mock()
        child.poll.return_value = None
        manager.child = child
        manager.started_at = time.monotonic() - 0.5
        manager.media_pause_started = time.monotonic() - 1.0
        safe = {"total_gb": 48, "free_percent": 75,
                "headroom_gb": 30, "used_estimate_gb": 12,
                "pressure": "normal"}
        with (tempfile.TemporaryDirectory() as directory,
              mock.patch.object(ctl, "STATE", Path(directory) / "state.json"),
              mock.patch.object(sup, "valid_settings", return_value=True),
              mock.patch.object(sup.rc, "memory_budget_snapshot",
                                return_value=safe),
              mock.patch.object(ctl, "active_media_kind", return_value=None),
              mock.patch.object(sup, "model_ready", return_value=True)):
            manager.tick()
            manager.tick()
            published = json.loads(ctl.STATE.read_text())
        self.assertEqual(published["state"], "running")
        self.assertEqual(published["performance"]["model_api_ready_ms"]["count"], 1)
        self.assertEqual(published["performance"]["media_resume_ms"]["count"], 1)
        self.assertGreater(published["performance"]["media_resume_ms"]["p50"], 0)
        self.assertNotIn("/Users/", json.dumps(published))


if __name__ == "__main__":
    unittest.main()
