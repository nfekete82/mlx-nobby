"""Quick web research must remain bounded; deep research is opt-in."""
import unittest
from agent.runtime import RuntimePolicy


class ResearchPolicyTests(unittest.TestCase):
    def test_quick_research_defaults_to_three_steps(self):
        policy = RuntimePolicy()
        self.assertEqual(policy.max_steps("research"), 3)
        self.assertEqual(policy.max_steps("coding"), 24)
        self.assertEqual(policy.max_steps("orchestrator"), 12)


if __name__ == "__main__":
    unittest.main()
