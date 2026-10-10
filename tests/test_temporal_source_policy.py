"""Regression checks for final-answer temporal source policy."""
import unittest

from agent.prompts import agent_v2_final_answer


class TemporalSourcePolicyTests(unittest.TestCase):
    def test_final_prompt_requires_dated_evidence_and_conflict_disclosure(self):
        calls = []

        def fake_llm(label, messages, **kwargs):
            calls.append((label, messages))
            return "Nicht verifiziert."

        agent_v2_final_answer(
            "Wann erscheint das nächste Smartphone und wie viel kostet es?",
            [],
            observed_agent_llm=fake_llm,
        )
        system = next(messages[0]["content"] for label, messages in calls
                      if label == "agent.final")
        for requirement in (
            "AKTUALITÄTS- UND PROGNOSEPRÜFUNG",
            "Ereignisdatum",
            "Widersprechen sich geladene Quellen",
            "unbestätigte Prognose",
            "nicht verifiziert",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, system)

    def test_no_external_tool_needed_for_simple_math(self):
        calls = []

        def fake_llm(label, messages, **kwargs):
            calls.append(label)
            return "391"

        answer = agent_v2_final_answer(
            "Was ist 17 × 23?", [], observed_agent_llm=fake_llm
        )
        self.assertEqual(answer, "391")
        self.assertIn("agent.final", calls)


if __name__ == "__main__":
    unittest.main()
