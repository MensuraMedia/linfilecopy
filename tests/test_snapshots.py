import os
import tempfile
import unittest

from linfilecopy.engine import snapshots


class RetentionTest(unittest.TestCase):
    def test_keeps_last_24h_daily_and_weekly(self) -> None:
        names = [
            "2026-09-28T030000", "2026-09-28T010000", "2026-09-27T200000",   # last 24 h: all kept
            "2026-09-27T010000",                                           # >24h, same day as a kept one
            "2026-09-26T030000", "2026-09-25T030000", "2026-09-24T030000",
            "2026-09-10T030000", "2026-09-03T030000", "2026-08-01T030000",
        ]
        removed = snapshots.select_to_remove(names, keep_daily=3, keep_weekly=3)
        self.assertNotIn("2026-09-28T010000", removed)
        self.assertNotIn("2026-09-27T200000", removed)
        self.assertIn("2026-09-27T010000", removed)
        self.assertIn("2026-09-25T030000", removed)          # beyond 3 daily
        self.assertNotIn("2026-09-10T030000", removed)       # a weekly keeper
        self.assertIn("2026-08-01T030000", removed)

    def test_protected_and_ignores_other_names(self) -> None:
        removed = snapshots.select_to_remove(["2020-01-01T000000", "2026-01-01T000000", "notes"], 1, 1,
                                             protect={"2020-01-01T000000"})
        self.assertEqual(removed, [])

    def test_update_latest_is_relative_and_replaces(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            for n in ("2026-01-01T000000", "2026-01-02T000000"):
                os.mkdir(os.path.join(d, n))
                snapshots.update_latest(d, n)
            self.assertEqual(os.readlink(os.path.join(d, "latest")), "2026-01-02T000000")
            self.assertEqual(snapshots.list_snapshots(d), ["2026-01-01T000000", "2026-01-02T000000"])


if __name__ == "__main__":
    unittest.main()
