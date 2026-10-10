"""Deterministic date/status safety checks."""
import unittest
from datetime import date
from agent.temporal_validation import future_availability_conflicts, gate_temporal_claims


class TemporalValidationTests(unittest.TestCase):
    def test_future_sale_and_already_available_is_flagged(self):
        answer = "iPhone Duo ist bereits erhältlich; erhältlich ab 23.10.2026."
        result = gate_temporal_claims(answer, today=date(2026, 10, 10))
        self.assertIn("Zeitprüfung", result)
        self.assertIn("2026-10-23", result)

    def test_real_iphone_duo_case_future_since_is_flagged(self):
        answer = "iPhone Duo (Neu, seit 23.10.2026)"
        self.assertIn("Zeitprüfung", gate_temporal_claims(answer, date(2026, 10, 10)))

    def test_announced_future_product_is_allowed(self):
        answer = "iPhone Duo wurde vorgestellt; erhältlich ab 23.10.2026."
        self.assertEqual(gate_temporal_claims(answer, date(2026, 10, 10)), answer)

    def test_past_sale_not_flagged(self):
        answer = "iPhone 18 ist bereits erhältlich; erhältlich ab 18.09.2026."
        self.assertEqual(gate_temporal_claims(answer, date(2026, 10, 10)), answer)

    def test_invalid_date_is_ignored(self):
        self.assertEqual(future_availability_conflicts(
            "Bereits erhältlich; erhältlich ab 38.19.2026.", date(2026, 10, 10)), [])

    def test_no_false_positive_without_explicit_availability(self):
        answer = "Apple zeigt aktuell iPhone Duo, verfügbar ab 23.10.2026."
        self.assertEqual(gate_temporal_claims(answer, date(2026, 10, 10)), answer)


if __name__ == "__main__":
    unittest.main()
