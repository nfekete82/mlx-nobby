import unittest
from dataclasses import replace

from model_idle_policy import IdleState, evaluate_idle_unload


class IdlePolicyTests(unittest.TestCase):
    def state(self, role="chat", **changes):
        baseline = IdleState(
            role=role,
            now=1000,
            last_activity=0,
            loaded=True,
            idle_verified=True,
            lease_free=True,
            active_requests=0,
            pending_requests=0,
            exclusive_session=False,
            server_identity_verified=True,
        )
        return replace(baseline, **changes)

    def test_chat_eligible_after_15_minutes(self):
        result = evaluate_idle_unload(self.state())
        self.assertTrue(result.allowed)

    def test_chat_not_eligible_before_15_minutes(self):
        result = evaluate_idle_unload(
            self.state(last_activity=101)
        )
        self.assertFalse(result.allowed)

    def test_router_eligible_after_5_minutes(self):
        result = evaluate_idle_unload(
            self.state("router", last_activity=700)
        )
        self.assertTrue(result.allowed)

    def test_router_not_eligible_before_5_minutes(self):
        result = evaluate_idle_unload(
            self.state("router", last_activity=701)
        )
        self.assertFalse(result.allowed)

    def test_blocks_active_requests(self):
        result = evaluate_idle_unload(
            self.state(active_requests=1)
        )
        self.assertFalse(result.allowed)

    def test_blocks_pending_requests(self):
        result = evaluate_idle_unload(
            self.state(pending_requests=1)
        )
        self.assertFalse(result.allowed)

    def test_blocks_active_lease(self):
        result = evaluate_idle_unload(
            self.state(lease_free=False)
        )
        self.assertFalse(result.allowed)

    def test_blocks_unverified_idle_state(self):
        result = evaluate_idle_unload(
            self.state(idle_verified=False)
        )
        self.assertFalse(result.allowed)

    def test_blocks_unverified_server(self):
        result = evaluate_idle_unload(
            self.state(server_identity_verified=False)
        )
        self.assertFalse(result.allowed)

    def test_blocks_exclusive_ltx_session(self):
        result = evaluate_idle_unload(
            self.state(exclusive_session=True)
        )
        self.assertFalse(result.allowed)

    def test_blocks_unknown_activity_time(self):
        result = evaluate_idle_unload(
            self.state(last_activity=None)
        )
        self.assertFalse(result.allowed)

    def test_blocks_clock_anomaly(self):
        result = evaluate_idle_unload(
            self.state(last_activity=1001)
        )
        self.assertFalse(result.allowed)

    def test_blocks_unknown_role(self):
        result = evaluate_idle_unload(
            self.state(role="video")
        )
        self.assertFalse(result.allowed)

    def test_blocks_unknown_request_counts(self):
        for value in (None, True, -1):
            with self.subTest(value=value):
                result = evaluate_idle_unload(
                    self.state(active_requests=value)
                )
                self.assertFalse(result.allowed)


if __name__ == "__main__":
    unittest.main()
