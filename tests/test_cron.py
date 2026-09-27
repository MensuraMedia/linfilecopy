import datetime as dt
import unittest

from linfilecopy.model import cron


class CronTest(unittest.TestCase):
    def test_parse_fields(self) -> None:
        spec = cron.parse("*/30 9-18 * * 1-5")
        self.assertEqual(spec.minutes, {0, 30})
        self.assertEqual(min(spec.hours), 9)
        self.assertEqual(spec.weekdays, {1, 2, 3, 4, 5})

    def test_names_and_sunday_seven(self) -> None:
        spec = cron.parse("0 20 * jan-mar sun,7")
        self.assertEqual(spec.months, {1, 2, 3})
        self.assertEqual(spec.weekdays, {0})

    def test_errors(self) -> None:
        for bad in ["", "* * * *", "60 * * * *", "* 24 * * *", "*/0 * * * *", "a * * * *", "5-1 * * * *", "1,,2 * * * *"]:
            with self.subTest(bad=bad), self.assertRaises(cron.CronError):
                cron.parse(bad)

    def test_next_after_weekday_evening(self) -> None:
        spec = cron.parse("0 20 * * 1-5")
        sat = dt.datetime(2026, 9, 26, 12, 0)  # Saturday
        self.assertEqual(spec.next_after(sat), dt.datetime(2026, 9, 28, 20, 0))  # Monday

    def test_next_after_dom_or_dow(self) -> None:
        spec = cron.parse("0 0 1 * mon")  # 1st of month OR Monday
        self.assertEqual(spec.next_after(dt.datetime(2026, 9, 27, 12, 0)), dt.datetime(2026, 9, 28, 0, 0))

    def test_next_after_rolls_months(self) -> None:
        spec = cron.parse("15 3 31 * *")
        self.assertEqual(spec.next_after(dt.datetime(2026, 9, 27)), dt.datetime(2026, 10, 31, 3, 15))


if __name__ == "__main__":
    unittest.main()
