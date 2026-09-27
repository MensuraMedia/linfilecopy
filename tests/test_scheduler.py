import datetime as dt
import tempfile
import unittest
from pathlib import Path

from linfilecopy.engine import scheduler as sc
from linfilecopy.model.enums import ScheduleBackend, ScheduleKind
from linfilecopy.model.job import SyncJob


def job(kind=ScheduleKind.DAILY, **kw) -> SyncJob:
    j = SyncJob(name="Home snapshot", id="home-snapshot-ab12")
    j.schedule.kind = kind
    j.schedule.enabled = True
    for k, v in kw.items():
        setattr(j.schedule, k, v)
    return j


class FakeRunner:
    def __init__(self, crontab: str = "") -> None:
        self.calls: list[list[str]] = []
        self.crontab = crontab

    def __call__(self, argv, stdin=None):
        self.calls.append(argv)
        if argv[:2] == ["crontab", "-l"]:
            return (0, self.crontab) if self.crontab else (1, "no crontab for user")
        if argv[:2] == ["crontab", "-"]:
            self.crontab = stdin or ""
            return 0, ""
        return 0, "HOME=/x\n" if argv[-1] == "show-environment" else ""


class CalendarTest(unittest.TestCase):
    def test_on_calendar(self) -> None:
        self.assertEqual(sc.on_calendar(job(time="03:00").schedule), "*-*-* 03:00:00")
        self.assertEqual(sc.on_calendar(job(ScheduleKind.WEEKLY, time="20:30", weekdays=[0, 2, 6]).schedule),
                         "Mon,Wed,Sun *-*-* 20:30:00")
        self.assertEqual(sc.on_calendar(job(ScheduleKind.HOURLY, minute=15).schedule), "*-*-* *:15:00")
        self.assertEqual(sc.on_calendar(job(ScheduleKind.ONCE, once_date="2026-10-01", time="09:00").schedule),
                         "2026-10-01 09:00:00")
        self.assertEqual(sc.on_calendar(job(ScheduleKind.CUSTOM, cron="*/30 9-18 * * 1-5").schedule),
                         "Mon..Fri *-*-* 09..18:00,30:00".replace("Mon..Fri", "Mon,Tue,Wed,Thu,Fri"))

    def test_dom_or_dow_not_expressible(self) -> None:
        with self.assertRaises(sc.ScheduleError):
            sc.on_calendar(job(ScheduleKind.CUSTOM, cron="0 0 1 * mon").schedule)

    def test_next_run_and_describe(self) -> None:
        j = job(ScheduleKind.WEEKLY, time="03:00", weekdays=[0])
        self.assertEqual(sc.next_run(j, dt.datetime(2026, 9, 27, 12)), dt.datetime(2026, 9, 28, 3, 0))
        self.assertEqual(sc.describe_schedule(j), "Mon at 03:00")
        j.schedule.enabled = False
        self.assertIsNone(sc.next_run(j))
        self.assertIn("paused", sc.describe_schedule(j))
        self.assertEqual(sc.describe_schedule(SyncJob()), "Not scheduled")


class BackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.units = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_systemd_install_and_remove(self) -> None:
        runner = FakeRunner()
        s = sc.Scheduler(self.units, runner, systemd_available=True, cron_available=True)
        self.assertEqual(s.apply(job()), ScheduleBackend.SYSTEMD)
        timer = (self.units / "linfilecopy-home-snapshot-ab12.timer").read_text()
        service = (self.units / "linfilecopy-home-snapshot-ab12.service").read_text()
        self.assertIn("OnCalendar=*-*-* 03:00:00", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("run home-snapshot-ab12", service)
        self.assertIn(["systemctl", "--user", "enable", "--now", "linfilecopy-home-snapshot-ab12.timer"], runner.calls)
        self.assertEqual(s.installed(), {"home-snapshot-ab12": ScheduleBackend.SYSTEMD})
        s.remove("home-snapshot-ab12")
        self.assertEqual(list(self.units.iterdir()), [])

    def test_auto_falls_back_to_cron_and_preserves_other_lines(self) -> None:
        runner = FakeRunner("MAILTO=me\n0 1 * * * /usr/bin/backup-other\n")
        s = sc.Scheduler(self.units, runner, systemd_available=False, cron_available=True)
        j = job(ScheduleKind.CUSTOM, cron="0 0 1 * mon")
        self.assertEqual(s.apply(j), ScheduleBackend.CRON)
        self.assertIn("/usr/bin/backup-other", runner.crontab)
        self.assertIn("# linfilecopy:home-snapshot-ab12 BEGIN", runner.crontab)
        self.assertIn("0 0 1 * mon ", runner.crontab)
        j.schedule.enabled = False
        s.apply(j)
        self.assertEqual(runner.crontab.count("BEGIN"), 1)
        self.assertIn("#disabled#", runner.crontab)
        s.remove(j.id)
        self.assertEqual(runner.crontab, "MAILTO=me\n0 1 * * * /usr/bin/backup-other\n")

    def test_none_removes_and_invalid_id_rejected(self) -> None:
        runner = FakeRunner()
        s = sc.Scheduler(self.units, runner, systemd_available=True, cron_available=False)
        s.apply(job())
        j = job(ScheduleKind.NONE)
        self.assertIsNone(s.apply(j))
        self.assertEqual(s.installed(), {})
        with self.assertRaises(sc.ScheduleError):
            s.remove("../evil")

    def test_nothing_available(self) -> None:
        s = sc.Scheduler(self.units, FakeRunner(), systemd_available=False, cron_available=False)
        with self.assertRaises(sc.ScheduleError):
            s.apply(job())


if __name__ == "__main__":
    unittest.main()
