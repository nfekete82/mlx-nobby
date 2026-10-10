"""Repair is bounded, verified again, and skipped without fetched evidence."""
import unittest
from agent.prompts import agent_v2_final_answer


def observations():
    return [{"action": "fetch_url", "status": "completed", "result": {
        "ok": True, "url": "https://example.org/phone",
        "text": "Pixel 11 kostet 999 €. " * 15}}]


class EvidenceRepairTests(unittest.TestCase):
    def test_repair_can_remove_unsupported_claim(self):
        calls = []
        def llm(label, messages, **kwargs):
            calls.append(label)
            return ("Pixel 11 kostet 1599 €." if label == "agent.final"
                    else "Pixel 11 kostet 999 €.")
        answer = agent_v2_final_answer("Preis Pixel 11?", observations(),
                                       observed_agent_llm=llm)
        self.assertIn("999 €", answer)
        self.assertNotIn("1599 €", answer)
        self.assertEqual(calls.count("agent.evidence_repair"), 1)

    def test_failed_repair_keeps_warning(self):
        def llm(label, messages, **kwargs):
            if label == "agent.evidence_repair":
                raise RuntimeError("model unavailable")
            return "Pixel 11 kostet 1599 €."
        answer = agent_v2_final_answer("Preis Pixel 11?", observations(),
                                       observed_agent_llm=llm)
        self.assertIn("nicht verifiziert", answer)

    def test_no_repair_without_web(self):
        calls = []
        def llm(label, messages, **kwargs):
            calls.append(label)
            return "391"
        answer = agent_v2_final_answer("17 × 23?", [], observed_agent_llm=llm)
        self.assertEqual(answer, "391")
        self.assertNotIn("agent.evidence_repair", calls)


if __name__ == "__main__":
    unittest.main()
