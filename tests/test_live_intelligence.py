"""Deterministic tests: offline, predictable, no external network."""
import io
import json
import unittest
from datetime import datetime, timezone
from backend.live_intelligence import retrieve_inflation, needs_inflation_lookup

class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, _limit):
        return json.dumps(self.payload).encode()

class LiveIntelligenceTests(unittest.TestCase):
    def test_trigger(self):
        self.assertTrue(needs_inflation_lookup("Wie viel muss mein Gehalt steigen, um die Inflation auszugleichen?"))
        self.assertTrue(needs_inflation_lookup("Inflationsrate 2025"))
        self.assertFalse(needs_inflation_lookup("Schreibe ein Gedicht über Birnbäume."))

    def test_live_results_include_source_and_dates(self):
        data = [{"page": 1}, [
            {"date": "2025", "value": 2.2}, {"date": "2024", "value": 2.2},
            {"date": "2023", "value": 5.9}, {"date": "2022", "value": 6.9}
        ]]
        result = retrieve_inflation("Inflation in den letzten 3 Jahren",
            opener=lambda request, timeout: FakeResponse(data),
            now=datetime(2026, 10, 10, tzinfo=timezone.utc))
        self.assertIn("2023: 5.90 %", result)
        self.assertIn("2025: 2.20 %", result)
        self.assertIn("2026-10-10", result)
        self.assertIn("World Bank", result)
        self.assertIn("nicht zwingend letzte 36 Monate", result)

    def test_offline_does_not_fabricate(self):
        def offline(request, timeout):
            raise OSError("offline")
        result = retrieve_inflation("Aktuelle Inflation Deutschland", opener=offline)
        self.assertIn("LIVE-DATENABRUF FEHLGESCHLAGEN", result)
        self.assertIn("Keine aktuellen Inflationsraten schätzen", result)

if __name__ == "__main__":
    unittest.main()
