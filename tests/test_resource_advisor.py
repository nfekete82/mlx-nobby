"""Read-only dashboard admission and 4B supervisor tests (no local model loads)."""
import json
import unittest
from unittest import mock

from agent import resource_advisor as advice
from agent import performance_observatory_routes as performance


class ResourceAdvisorTests(unittest.TestCase):
    def setUp(self):
        self.budget = {
            "total_gb": 48.0, "free_percent": 65.0,
            "headroom_gb": 25.0, "pressure": "normal",
            "used_estimate_gb": 16.8,
        }

    def test_running_supervisor_visible_with_no_private_model_path(self):
        with mock.patch.object(advice.memory_model_coordination, "supervisor_state",
                               return_value={"state": "running", "owned": True,
                                             "pause_extraction": False,
                                             "model": "/Users/private/checkpoint"}):
            output = advice.snapshot(self.budget)
        self.assertEqual(output["memory4b"]["state"], "warm")
        self.assertTrue(output["memory4b"]["managed"])
        self.assertFalse(output["memory4b"]["paused"])
        self.assertEqual(output["memory4b"]["model"], "Qwen3.5-4B")
        self.assertNotIn("/Users/private/", json.dumps(output))

    def test_media_handoff_pause_is_not_reported_as_ready(self):
        with mock.patch.object(advice.memory_model_coordination, "supervisor_state",
                               return_value={"state": "suspended_media", "owned": False,
                                             "pause_extraction": True}):
            output = advice.snapshot(self.budget)["memory4b"]
        self.assertEqual(output["state"], "cold")
        self.assertTrue(output["paused"])
        self.assertFalse(output["available"])

    def test_external_server_is_not_claimed_as_managed(self):
        with mock.patch.object(advice.memory_model_coordination, "supervisor_state",
                               return_value={"state": "external", "owned": False}):
            output = advice.snapshot(self.budget)["memory4b"]
        self.assertEqual(output["supervisor_state"], "external")
        self.assertEqual(output["state"], "unavailable")
        self.assertFalse(output["managed"])

    def test_unknown_and_invalid_state_not_exposed(self):
        with mock.patch.object(advice.memory_model_coordination, "supervisor_state",
                               return_value={"state": "/Users/private/secret",
                                             "owned": True}):
            output = advice.snapshot(self.budget)
        self.assertEqual(output["memory4b"]["supervisor_state"], "not_installed")
        self.assertNotIn("secret", json.dumps(output))

    def test_high_pressure_prompts_model_release(self):
        low = {"total_gb": 48.0, "free_percent": 10.0,
               "headroom_gb": 0.0, "pressure": "elevated",
               "used_estimate_gb": 43.2}
        with mock.patch.object(advice.memory_model_coordination, "supervisor_state",
                               return_value={}):
            output = advice.snapshot(low)
        self.assertEqual(output["admission"]["image"]["state"], "release_required")
        self.assertEqual(output["admission"]["video"]["state"], "release_required")

    def test_healthy_headroom_does_not_propose_unnecessary_release(self):
        with mock.patch.object(advice.memory_model_coordination, "supervisor_state",
                               return_value={}):
            output = advice.snapshot(self.budget)
        self.assertEqual(output["admission"]["image"]["state"], "headroom_ok")
        self.assertEqual(output["admission"]["video"]["state"], "headroom_ok")

    def test_unmeasured_pressure_is_unknown_not_zero(self):
        with mock.patch.object(advice.memory_model_coordination, "supervisor_state",
                               return_value={}):
            output = advice.snapshot({"free_percent": None})
        self.assertEqual(output["admission"]["image"]["state"], "unknown")

    def test_performance_uses_cached_memory_budget_without_new_probe(self):
        runtime = {"chat": {"state": "warm"}, "image": {"state": "cold"},
                   "video": {"state": "cold"}}
        queue = {"jobs": [], "active_count": 0, "waiting_count": 0,
                 "runtime": {"memory": self.budget, "waiting": []}}
        with (mock.patch.object(performance.media_queue, "snapshot",
                                return_value=queue),
              mock.patch.object(performance, "runtime_snapshot",
                                return_value=runtime),
              mock.patch.object(performance.runtime_coordinator,
                                "memory_budget_snapshot",
                                side_effect=AssertionError("unexpected RAM probe")),
              mock.patch.object(advice.memory_model_coordination, "supervisor_state",
                                return_value={"state": "running", "owned": True})):
            output = performance.build_performance_snapshot(limit=10)
        self.assertEqual(output["system"]["runtimes"]["memory4b"]["state"], "warm")
        self.assertEqual(output["system"]["admission"]["image"]["state"], "headroom_ok")
        self.assertEqual(output["system"]["memory"], self.budget)


if __name__ == "__main__":
    unittest.main()
