import os
import unittest

from linfilecopy.model.enums import DriveKind, Mode, ScheduleKind
from linfilecopy.model.job import FilterRule, SyncJob
from linfilecopy.model.validation import ERROR, WARNING, has_errors, validate_job


def job(src="/home/sam/Documents", dst="/media/sam/USB/Documents", **kw) -> SyncJob:
    j = SyncJob(name="t")
    j.source.path, j.destination.path = src, dst
    for k, v in kw.items():
        setattr(j, k, v)
    return j


def fields(j: SyncJob, level: str = ERROR) -> set[str]:
    return {i.field for i in validate_job(j) if i.level == level}


class ValidationTest(unittest.TestCase):
    def test_valid_basic_job(self) -> None:
        self.assertFalse(has_errors(validate_job(job())))

    def test_missing_and_relative_paths(self) -> None:
        self.assertEqual(fields(job("", "")) & {"source.path", "destination.path"}, {"source.path", "destination.path"})
        self.assertIn("source.path", fields(job("Documents")))
        j = job(); j.name = " "
        self.assertIn("name", fields(j))

    def test_same_and_nested_paths(self) -> None:
        self.assertIn("destination.path", fields(job("/a/b", "/a/b/")))
        self.assertIn("destination.path", fields(job("/a", "/a/backup")))
        self.assertNotIn("destination.path", fields(job("/a/b", "/a/bc")))  # prefix, not inside

    def test_source_inside_destination(self) -> None:
        self.assertIn("destination.path", fields(job("/mnt/b/data/photos", "/mnt/b/data", mode=Mode.MIRROR)))
        self.assertIn("destination.path", fields(job("/mnt/b/data/photos", "/mnt/b/data", mode=Mode.TWO_WAY)))
        self.assertIn("destination.path", fields(job("/mnt/b/data/photos", "/mnt/b/data"), WARNING))

    def test_mount_roots_protected(self) -> None:
        for d in ("/media/sam", "/run/media/sam", "/media"):
            self.assertIn("destination.path", fields(job(src="/data", dst=d, mode=Mode.MIRROR)), d)
        self.assertNotIn("destination.path", fields(job(src="/data", dst="/media/sam/USB/backup", mode=Mode.MIRROR)))

    def test_parallel_with_files_from_blocked(self) -> None:
        j = job(); j.performance.parallel_streams = 2; j.filters.files_from = "/home/x/list"
        self.assertIn("performance.parallel_streams", fields(j))

    def test_mirror_into_protected_folder_blocked(self) -> None:
        self.assertIn("destination.path", fields(job(dst="/", mode=Mode.MIRROR)))
        self.assertIn("destination.path", fields(job(src="/data", dst=os.path.expanduser("~"), mode=Mode.MIRROR)))
        # Copy never deletes, so a protected destination is allowed.
        self.assertNotIn("destination.path", fields(job(src="/data", dst="/", mode=Mode.COPY)))

    def test_two_way_incompatibilities(self) -> None:
        j = job(mode=Mode.TWO_WAY); j.safety.snapshots = True; j.performance.parallel_streams = 4
        self.assertTrue({"mode", "performance.parallel_streams"} <= fields(j))

    def test_snapshot_and_inplace_combinations(self) -> None:
        j = job(); j.safety.snapshots = True; j.safety.atomic = True; j.transfer.inplace = True
        self.assertTrue({"safety.atomic", "transfer.inplace"} <= fields(j))
        j = job(); j.safety.snapshots = True; j.performance.parallel_streams = 2
        self.assertIn("performance.parallel_streams", fields(j))

    def test_owner_warning(self) -> None:
        j = job(); j.metadata.owner = True
        self.assertIn("metadata.owner", fields(j, WARNING))

    def test_filters(self) -> None:
        j = job(); j.filters.rules = [FilterRule(pattern="  ")]; j.filters.exclude_from = "list.txt"
        self.assertTrue({"filters.rules.0", "filters.exclude_from"} <= fields(j))

    def test_drive_options_need_a_picked_drive(self) -> None:
        j = job(); j.drive.unlock_encrypted = True; j.triggers.on_drive_connected = True
        self.assertTrue({"drive.unlock_encrypted", "triggers.on_drive_connected"} <= fields(j))
        j.destination.volume_uuid = "uuid"
        self.assertFalse({"drive.unlock_encrypted", "triggers.on_drive_connected"} & fields(j))

    def test_eject_warning_without_removable(self) -> None:
        j = job(); j.drive.eject_after = True
        self.assertIn("drive.eject_after", fields(j, WARNING))
        j.destination.kind = DriveKind.REMOVABLE
        self.assertNotIn("drive.eject_after", fields(j, WARNING))

    def test_schedule_checks(self) -> None:
        j = job(); j.schedule.kind = ScheduleKind.DAILY; j.schedule.time = "25:00"
        self.assertIn("schedule.time", fields(j))
        j.schedule.kind = ScheduleKind.WEEKLY; j.schedule.time = "03:00"; j.schedule.weekdays = []
        self.assertIn("schedule.weekdays", fields(j))
        j.schedule.kind = ScheduleKind.CUSTOM; j.schedule.cron = "61 * * * *"
        self.assertIn("schedule.cron", fields(j))
        j.schedule.cron = "*/30 9-18 * * 1-5"
        self.assertNotIn("schedule.cron", fields(j))

    def test_every_issue_has_message(self) -> None:
        j = job("", "", mode=Mode.TWO_WAY)
        for issue in validate_job(j):
            self.assertTrue(issue.message)


if __name__ == "__main__":
    unittest.main()
