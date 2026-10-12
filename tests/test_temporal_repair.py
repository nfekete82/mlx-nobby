"""Regression tests for conservative future date correction."""
import unittest
from datetime import date
from agent.temporal_repair import correct_future_availability
from agent.temporal_validation import gate_temporal_claims

TODAY = date(2026, 10, 10)


class TemporalRepairTests(unittest.TestCase):
    def test_actual_iphone_duo_line(self):
        line = "1. **iPhone Duo** (Neu, seit 23. Oktober 2026) – faltbar"
        fixed = correct_future_availability(line, TODAY)
        self.assertIn("laut genanntem Termin erst ab 23. Oktober 2026", fixed)
        self.assertNotIn("seit 23. Oktober", fixed)
        self.assertEqual(gate_temporal_claims(fixed, TODAY), fixed)

    def test_numeric_future_date(self):
        self.assertIn("erst ab 23.10.2026",
                      correct_future_availability("Neu, seit 23.10.2026", TODAY))

    def test_announced_future_remains_unchanged(self):
        text = "Angekündigt, erhältlich ab 23. Oktober 2026."
        self.assertEqual(correct_future_availability(text, TODAY), text)

    def test_past_since_remains_unchanged(self):
        text = "Erhältlich seit 18. September 2026."
        self.assertEqual(correct_future_availability(text, TODAY), text)

    def test_current_future_contradiction(self):
        text = "Bereits erhältlich; erhältlich ab 23.10.2026."
        fixed = correct_future_availability(text, TODAY)
        self.assertIn("noch nicht erhältlich", fixed)
        self.assertEqual(gate_temporal_claims(fixed, TODAY), fixed)

    def test_idempotent(self):
        line = "Neu, seit 23. Oktober 2026."
        once = correct_future_availability(line, TODAY)
        self.assertEqual(correct_future_availability(once, TODAY), once)

    def test_future_accessory_does_not_repair_current_product(self):
        text = "Bereits erhältlich; erhältlich ab 18.09.2026, Zubehör vorbestellbar ab 23.10.2026."
        self.assertEqual(correct_future_availability(text, TODAY), text)


if __name__ == "__main__":
    unittest.main()
