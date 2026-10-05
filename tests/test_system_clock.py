import unittest
from datetime import datetime, timedelta, timezone

from agent import system_clock


class SystemClockTests(unittest.TestCase):
    def test_snapshot_preserves_local_date_time_zone_and_offset(self):
        local = datetime(
            2026, 10, 5, 8, 56, 33,
            tzinfo=timezone(timedelta(hours=2), "CEST"),
        )

        result = system_clock.snapshot(local)

        self.assertEqual(result, {
            "iso": "2026-10-05T08:56:33+02:00",
            "date": "2026-10-05",
            "time": "08:56:33",
            "timezone": "CEST",
            "utc_offset": "+02:00",
        })

    def test_context_marks_host_clock_authoritative_for_relative_time(self):
        local = datetime(
            2026, 10, 5, 8, 56, 33,
            tzinfo=timezone(timedelta(hours=2), "CEST"),
        )

        context = system_clock.context(local)

        self.assertIn("CURRENT HOST SYSTEM TIME", context)
        self.assertIn("2026-10-05T08:56:33+02:00", context)
        self.assertIn("Timezone: CEST", context)
        self.assertIn("UTC offset: +02:00", context)
        self.assertIn("authoritative for the current turn", context)
        self.assertIn("ages", context)
        self.assertIn("this year", context)
        self.assertIn("Do not infer the current date or time", context)

    def test_each_call_uses_the_supplied_turn_snapshot(self):
        first = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        second = datetime(2027, 1, 1, 0, 0, 1, tzinfo=timezone.utc)

        self.assertIn("2026-12-31", system_clock.context(first))
        self.assertIn("2027-01-01", system_clock.context(second))


if __name__ == "__main__":
    unittest.main()
