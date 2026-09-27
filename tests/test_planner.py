import datetime as dt
import unittest

from linfilecopy.engine.drives import DriveInfo, EndpointState, ResolvedEndpoint
from linfilecopy.engine.filesystems import capabilities_for
from linfilecopy.engine.planner import PlanEnv, StepKind, plan_job
from linfilecopy.model.enums import DriveKind, Mode
from linfilecopy.model.job import SyncJob


def job(**kw) -> SyncJob:
    j = SyncJob(name="t")
    j.source.path, j.destination.path = "/home/sam/Docs", "/media/sam/USB/Docs"
    for k, v in kw.items():
        setattr(j, k, v)
    return j


def env(fs="ext4", **kw) -> PlanEnv:
    base = dict(source=ResolvedEndpoint("/home/sam/Docs", EndpointState.READY),
                destination=ResolvedEndpoint("/media/sam/USB/Docs", EndpointState.READY),
                dest_fs=capabilities_for(fs), now=dt.datetime(2026, 9, 28, 3, 0, 0))
    base.update(kw)
    return PlanEnv(**base)


def kinds(plan) -> list[StepKind]:
    return [s.kind for s in plan.steps]


class PlannerTest(unittest.TestCase):
    def test_simple_copy(self) -> None:
        p = plan_job(job(), env())
        self.assertTrue(p.runnable)
        self.assertEqual(kinds(p), [StepKind.RSYNC])
        self.assertEqual(p.steps[0].argv[-2:], ["/home/sam/Docs/", "/media/sam/USB/Docs/"])
        self.assertNotIn("#", p.display_text())

    def test_exfat_adjustment_reported(self) -> None:
        p = plan_job(job(), env("exfat"))
        info = [i for i in p.issues if i.field == "destination.fs"]
        self.assertEqual(info[0].message, "Adjusted for exFAT")
        self.assertIn("permissions", info[0].fix)
        self.assertEqual(p.steps[0].argv[1], "-rt")

    def test_snapshots_on_exfat_blocked(self) -> None:
        j = job(); j.safety.snapshots = True
        p = plan_job(j, env("exfat"))
        self.assertFalse(p.runnable)

    def test_snapshot_steps(self) -> None:
        j = job(); j.safety.snapshots = True
        p = plan_job(j, env(latest_snapshot_exists=True))
        self.assertEqual(kinds(p), [StepKind.RSYNC, StepKind.UPDATE_LATEST, StepKind.ROTATE])
        a = p.steps[0].argv
        self.assertIn("--link-dest=/media/sam/USB/Docs/latest", a)
        self.assertEqual(a[-1], "/media/sam/USB/Docs/2026-09-28T030000.incomplete/")
        self.assertTrue(p.display_text().startswith("# 1. copy into a new snapshot"))
        first = plan_job(j, env(latest_snapshot_exists=False))
        self.assertFalse(any(x.startswith("--link-dest") for x in first.steps[0].argv))

    def test_snapshot_preview_compares_with_latest(self) -> None:
        j = job(); j.safety.snapshots = True
        p = plan_job(j, env(latest_snapshot_exists=True), preview=True)
        self.assertEqual(kinds(p), [StepKind.RSYNC])
        self.assertEqual(p.steps[0].argv[-1], "/media/sam/USB/Docs/latest/")

    def test_atomic_steps(self) -> None:
        j = job(); j.safety.atomic = True
        p = plan_job(j, env())
        self.assertEqual(kinds(p), [StepKind.HARDLINK_CLONE, StepKind.RSYNC, StepKind.SWAP, StepKind.REMOVE_TREE])
        self.assertEqual(p.steps[1].argv[-1], "/media/sam/USB/.Docs.lfc-stage/")
        fresh = plan_job(j, env(dest_exists=False))
        self.assertEqual(kinds(fresh), [StepKind.RSYNC, StepKind.SWAP])

    def test_parallel_and_two_way(self) -> None:
        j = job(); j.performance.parallel_streams = 4
        self.assertEqual(kinds(plan_job(j, env())), [StepKind.PARALLEL_RSYNC])
        self.assertEqual(kinds(plan_job(j, env(), preview=True)), [StepKind.RSYNC])
        self.assertEqual(kinds(plan_job(job(mode=Mode.TWO_WAY), env())), [StepKind.TWOWAY])

    def test_low_priority_wrapper(self) -> None:
        j = job(); j.performance.low_priority = True
        self.assertEqual(plan_job(j, env()).steps[0].argv[:5], ["ionice", "-c3", "nice", "-n19", "rsync"])
        self.assertEqual(plan_job(j, env(), preview=True).steps[0].argv[0], "rsync")
        p = plan_job(j, env(has_ionice=False, has_nice=False))
        self.assertEqual(p.steps[0].argv[0], "rsync")
        self.assertTrue(any(i.field == "performance.low_priority" for i in p.issues))

    def test_drive_steps_unlock_mount_eject(self) -> None:
        container = DriveInfo("/b/md0", "/dev/md0", "luks", "Archive", "crypto_LUKS", 1, encrypted=True, locked=True)
        usb = DriveInfo("/b/sdb1", "/dev/sdb1", "usb-uuid", "Stick", "exfat", 1, kind=DriveKind.REMOVABLE)
        j = job(); j.drive.unlock_encrypted = True; j.drive.eject_after = True
        j.destination.volume_uuid = "usb-uuid"; j.destination.kind = DriveKind.REMOVABLE; j.destination.volume_label = "Stick"
        e = env(source=ResolvedEndpoint("/mnt/archive", EndpointState.LOCKED, None, container),
                destination=ResolvedEndpoint("/media/sam/USB/Docs", EndpointState.NOT_MOUNTED, usb))
        p = plan_job(j, e)
        self.assertEqual(kinds(p), [StepKind.UNLOCK, StepKind.MOUNT, StepKind.RSYNC, StepKind.UNMOUNT, StepKind.POWER_OFF])
        # previews never touch drives
        self.assertEqual(kinds(plan_job(j, e, preview=True)), [StepKind.RSYNC])

    def test_missing_drive_and_locked_without_unlock(self) -> None:
        j = job(); j.destination.volume_uuid = "x"; j.destination.volume_label = "Stick"
        p = plan_job(j, env(destination=ResolvedEndpoint("/x", EndpointState.MISSING)))
        self.assertFalse(p.runnable)
        self.assertIn("Connect Stick", [i.message for i in p.issues if i.blocking][0])
        j.drive.wait_for_drive = True
        self.assertTrue(plan_job(j, env(destination=ResolvedEndpoint("/x", EndpointState.MISSING))).runnable)
        c = DriveInfo("/b/md0", "/dev/md0", "luks", "Archive", "crypto_LUKS", 1, encrypted=True, locked=True)
        p2 = plan_job(job(), env(destination=ResolvedEndpoint("/x", EndpointState.LOCKED, None, c)))
        self.assertFalse(p2.runnable)

    def test_missing_rsync_and_source(self) -> None:
        p = plan_job(job(), env(rsync_path=None, rsync_version=None, source_exists=False))
        fields = {i.field for i in p.issues if i.blocking}
        self.assertTrue({"engine", "source.path"} <= fields)


if __name__ == "__main__":
    unittest.main()
