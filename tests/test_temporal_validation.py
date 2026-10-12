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

    def test_real_month_name_future_since_is_flagged(self):
        answer = "3. **iPhone Duo** (Neu, seit 23. Oktober 2026 – faltbar)"
        self.assertIn("Zeitprüfung", gate_temporal_claims(answer, date(2026, 10, 10)))

    def test_future_announced_month_name_is_not_flagged(self):
        answer = "iPhone Duo: vorbestellbar ab 16. Oktober, erhältlich ab 23. Oktober 2026."
        self.assertEqual(gate_temporal_claims(answer, date(2026, 10, 10)), answer)

    def test_guard_is_idempotent(self):
        answer = "iPhone Duo (Neu, seit 23. Oktober 2026)"
        first = gate_temporal_claims(answer, date(2026, 10, 10))
        self.assertEqual(gate_temporal_claims(first, date(2026, 10, 10)), first)

    def test_real_diagnostic_answer_excerpt(self):
        answer = ("Apple bietet aktuell (Stand 10. Oktober 2026) sechs Modelle an:\n"
                  "1. **iPhone Duo** (Neu, seit 23. Oktober 2026) – faltbar")
        result = gate_temporal_claims(answer, date(2026, 10, 10))
        self.assertIn("**Zeitprüfung:**", result)

    def test_announced_future_product_is_allowed(self):
        answer = "iPhone Duo wurde vorgestellt; erhältlich ab 23.10.2026."
        self.assertEqual(gate_temporal_claims(answer, date(2026, 10, 10)), answer)

    def test_past_sale_not_flagged(self):
        answer = "iPhone 18 ist bereits erhältlich; erhältlich ab 18.09.2026."
        self.assertEqual(gate_temporal_claims(answer, date(2026, 10, 10)), answer)

    def test_invalid_date_is_ignored(self):
        self.assertEqual(future_availability_conflicts(
            "Bereits erhältlich; erhältlich ab 38.19.2026.", date(2026, 10, 10)), [])

    def test_iso_and_english_dates_are_checked(self):
        for answer in ("Jetzt verfügbar; Verkaufsstart 2026-10-23.",
                       "Already available; available from October 23, 2026.",
                       "Neu, seit 2026-10-23."):
            self.assertTrue(future_availability_conflicts(answer, date(2026, 10, 10)))

    def test_future_preorder_does_not_change_past_sale(self):
        answer = "Bereits erhältlich; erhältlich ab 18.09.2026, Zubehör vorbestellbar ab 23.10.2026."
        self.assertFalse(future_availability_conflicts(answer, date(2026, 10, 10)))

    def test_negated_current_availability_is_not_a_conflict(self):
        answer = "Noch nicht aktuell erhältlich; erhältlich ab 23.10.2026."
        self.assertFalse(future_availability_conflicts(answer, date(2026, 10, 10)))

    def test_no_false_positive_without_explicit_availability(self):
        answer = "Apple zeigt aktuell iPhone Duo, verfügbar ab 23.10.2026."
        self.assertEqual(gate_temporal_claims(answer, date(2026, 10, 10)), answer)


if __name__ == "__main__":
    unittest.main()
