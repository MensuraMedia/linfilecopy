"""End-to-end runs with the real rsync on temporary folders (no drives, no GUI)."""
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from linfilecopy.engine import tools
from linfilecopy.engine.progress import ChangeKind
from linfilecopy.engine.runner import EngineServices, JobRun, RunHooks, RunManager
from linfilecopy.model.enums import ConflictPolicy, Mode, RunStatus
from linfilecopy.model.history import HistoryStore
from linfilecopy.model.job import SyncJob

_env_backup: dict = {}


def setUpModule() -> None:
    tmp = tempfile.mkdtemp(prefix="lfc-test-home-")
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        _env_backup[var] = os.environ.get(var)
        os.environ[var] = os.path.join(tmp, var.lower())


def tearDownModule() -> None:
    for var, value in _env_backup.items():
        if value is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = value


def write(path: Path, text: str = "x", mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


@unittest.skipUnless(shutil.which("rsync"), "rsync not installed")
class RunnerTestBase(unittest.TestCase):
    caps = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.caps = tools.detect(udisks_probe=lambda: False)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src, self.dst = self.root / "src", self.root / "dst"
        self.src.mkdir()
        self.history = HistoryStore(self.root / "history.db")
        self.services = EngineServices(history=self.history, udisks=None, capabilities=self.caps)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def job(self, **kw) -> SyncJob:
        j = SyncJob(name="test", preview_first=False)
        j.source.path, j.destination.path = str(self.src), str(self.dst)
        j.filters.presets = []
        for k, v in kw.items():
            setattr(j, k, v)
        return j.ensure_identity()

    def run_job(self, job: SyncJob, preview=False, timeout=30, hooks=None) -> JobRun:
        run = JobRun(job, self.services, hooks or RunHooks(), preview=preview)
        run.start()
        run.join(timeout)
        self.assertFalse(run.active, f"run still active: {run.status}")
        return run


class BasicRunTest(RunnerTestBase):
    def test_copy_records_history_and_progress(self) -> None:
        write(self.src / "a.txt", "hello")
        write(self.src / "sub" / "b.bin", "x" * 50_000)
        updates = []
        run = self.run_job(self.job(), hooks=RunHooks(on_update=lambda r: updates.append(r.status)))
        self.assertEqual(run.status, RunStatus.SUCCESS, run.message + run.fix)
        self.assertEqual((self.dst / "sub" / "b.bin").read_text(), "x" * 50_000)
        self.assertGreaterEqual(run.snapshot.files_done, 2)
        self.assertGreater(run.snapshot.bytes_done, 50_000 - 1)
        rec = self.history.get(run.id)
        self.assertEqual(rec.status, RunStatus.SUCCESS)
        self.assertIn("rsync", rec.command)
        self.assertTrue(os.path.exists(rec.log_path))
        self.assertIn(RunStatus.RUNNING, updates)

    def test_preview_lists_changes_and_changes_nothing(self) -> None:
        write(self.src / "new.txt")
        write(self.dst / "old.txt")
        run = self.run_job(self.job(mode=Mode.MIRROR), preview=True)
        self.assertEqual(run.status, RunStatus.SUCCESS)
        kinds = {(c.kind, c.path) for c in run.changes}
        self.assertIn((ChangeKind.NEW, "new.txt"), kinds)
        self.assertIn((ChangeKind.DELETE, "old.txt"), kinds)
        self.assertFalse((self.dst / "new.txt").exists())
        self.assertTrue(self.history.get(run.id).dry_run)

    def test_mirror_deletes_copy_does_not(self) -> None:
        write(self.src / "keep.txt")
        write(self.dst / "extra.txt")
        self.run_job(self.job(mode=Mode.COPY))
        self.assertTrue((self.dst / "extra.txt").exists())
        self.run_job(self.job(mode=Mode.MIRROR))
        self.assertFalse((self.dst / "extra.txt").exists())

    def test_missing_source_fails_with_fix(self) -> None:
        j = self.job()
        j.source.path = str(self.root / "nope")
        run = self.run_job(j)
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertIn("does not exist", run.message)
        self.assertTrue(run.fix)

    def test_pause_resume_and_cancel(self) -> None:
        write(self.src / "big.bin", "y" * 3_000_000)
        j = self.job()
        j.performance.limit_speed, j.performance.speed_limit = True, 400  # KiB/s with KB unit below
        from linfilecopy.model.enums import SpeedUnit
        j.performance.speed_unit = SpeedUnit.KB
        run = JobRun(j, self.services)
        run.start()
        deadline = time.time() + 10
        while not run._procs and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.3)
        self.assertTrue(run.pause())
        self.assertEqual(run.status, RunStatus.PAUSED)
        time.sleep(0.3)
        self.assertTrue(run.resume())
        time.sleep(0.2)
        run.cancel()
        run.join(15)
        self.assertEqual(run.status, RunStatus.CANCELLED)


class StrategyTest(RunnerTestBase):
    def test_snapshots_share_unchanged_files(self) -> None:
        write(self.src / "same.txt", "same")
        write(self.src / "changes.txt", "v1")
        j = self.job()
        j.safety.snapshots = True
        self.run_job(j)
        time.sleep(1.1)  # snapshot names have one-second resolution
        write(self.src / "changes.txt", "v2")
        run = self.run_job(j)
        self.assertEqual(run.status, RunStatus.SUCCESS, run.message)
        snaps = sorted(p for p in self.dst.iterdir() if p.name[0].isdigit())
        self.assertEqual(len(snaps), 2)
        self.assertEqual(os.readlink(self.dst / "latest"), snaps[-1].name)
        self.assertEqual((snaps[0] / "same.txt").stat().st_ino, (snaps[1] / "same.txt").stat().st_ino)
        self.assertEqual((snaps[1] / "changes.txt").read_text(), "v2")
        self.assertEqual((snaps[0] / "changes.txt").read_text(), "v1")

    def test_atomic_replace(self) -> None:
        write(self.src / "a.txt", "new")
        write(self.dst / "a.txt", "old", mtime=time.time() - 3600)
        write(self.dst / "only-in-dst.txt", "kept in copy mode")
        j = self.job()
        j.safety.atomic = True
        run = self.run_job(j)
        self.assertEqual(run.status, RunStatus.SUCCESS, run.message)
        self.assertEqual((self.dst / "a.txt").read_text(), "new")
        self.assertTrue((self.dst / "only-in-dst.txt").exists())
        self.assertEqual([p.name for p in self.root.iterdir() if "lfc-stage" in p.name], [])

    def test_parallel_mirror(self) -> None:
        for d in ("one", "two", "three"):
            write(self.src / d / "f.bin", d * 1000)
        write(self.src / "top.txt")
        write(self.dst / "stale" / "x.txt")
        j = self.job(mode=Mode.MIRROR)
        j.performance.parallel_streams = 2
        run = self.run_job(j)
        self.assertEqual(run.status, RunStatus.SUCCESS, run.message)
        for d in ("one", "two", "three"):
            self.assertTrue((self.dst / d / "f.bin").exists())
        self.assertFalse((self.dst / "stale").exists())


class DesktopTestRegressionTest(RunnerTestBase):
    """Found testing on a real desktop with a USB stick (2026-09-28)."""

    def test_nested_missing_destination_is_created(self) -> None:
        write(self.src / "a.txt", "a")
        j = self.job()
        j.destination.path = str(self.root / "stick" / "LinFileCopy-test" / "Documents")
        run = self.run_job(j)
        self.assertEqual(run.status, RunStatus.SUCCESS, run.message + run.fix)
        self.assertTrue((self.root / "stick" / "LinFileCopy-test" / "Documents" / "a.txt").exists())

    def test_never_creates_folders_where_a_drive_should_be_mounted(self) -> None:
        from linfilecopy.engine.runner import ensure_parent

        for dest in ("/media/nobody-lfc-test/USB/x", "/mnt/lfc-missing-drive/x", "/run/media/nobody-lfc-test/USB/x"):
            self.assertIsNotNone(ensure_parent(dest), dest)
        self.assertFalse(os.path.exists("/media/nobody-lfc-test"))

    def test_failed_run_does_not_eject_the_drive(self) -> None:
        from linfilecopy.engine.drives import DriveInfo
        from linfilecopy.model.enums import DriveKind

        mount = self.root / "usb"
        mount.mkdir()
        calls: list[str] = []
        drive = DriveInfo("/fake/sdb1", "/dev/sdb1", "FAKE-1", "Stick", "ext4", 10**9, (str(mount),),
                          DriveKind.REMOVABLE, drive_path="/fake/drive", can_power_off=True)

        class FakeUDisks:
            def list_drives(self):  # noqa: D401
                return [drive]

            def unmount(self, d):
                calls.append("unmount")

            def power_off(self, d):
                calls.append("power_off")

        write(self.src / "ok.txt", "x")
        secret = self.src / "secret.txt"
        write(secret, "no")
        os.chmod(secret, 0)
        try:
            j = self.job()
            j.destination.path = str(mount / "backup")
            j.destination.volume_uuid, j.destination.relative_path = "FAKE-1", "backup"
            j.destination.kind, j.destination.volume_label = DriveKind.REMOVABLE, "Stick"
            j.drive.eject_after = True
            self.services.udisks = FakeUDisks()
            run = self.run_job(j)
        finally:
            os.chmod(secret, 0o644)
        if os.geteuid() != 0:
            self.assertEqual(run.status, RunStatus.FAILED)
            self.assertEqual(calls, [])
        # and a successful run does eject
        os.unlink(secret)
        calls.clear()
        run = self.run_job(j)
        self.assertEqual(run.status, RunStatus.SUCCESS, run.message)
        self.assertEqual(calls, ["unmount", "power_off"])


class SafetyRegressionTest(RunnerTestBase):
    def test_parallel_copy_folder_itself_goes_into_named_subfolder(self) -> None:
        write(self.src / "a" / "x.txt", "x")
        write(self.src / "#b.txt", "b")
        write(self.dst / "src" / "stale.txt", "old")
        write(self.dst / "keep-me.txt", "outside the mirrored folder")
        j = self.job(mode=Mode.MIRROR)
        j.transfer.copy_contents = False
        j.performance.parallel_streams = 2
        run = self.run_job(j)
        self.assertEqual(run.status, RunStatus.SUCCESS, run.message)
        self.assertTrue((self.dst / "src" / "a" / "x.txt").exists())
        self.assertTrue((self.dst / "src" / "#b.txt").exists())
        self.assertFalse((self.dst / "src" / "stale.txt").exists())
        self.assertTrue((self.dst / "keep-me.txt").exists())
        self.assertFalse((self.dst / "a").exists())

    def test_mirror_from_empty_source_refused(self) -> None:
        write(self.dst / "important.txt", "x")
        run = self.run_job(self.job(mode=Mode.MIRROR))
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertTrue((self.dst / "important.txt").exists())

    def test_failed_snapshot_is_not_kept_as_complete(self) -> None:
        write(self.src / "f.txt", "1")
        j = self.job()
        j.safety.snapshots = True
        self.run_job(j)
        good = [p.name for p in self.dst.iterdir() if p.name[0].isdigit()]
        self.assertEqual(len(good), 1)
        self.assertFalse(any(p.name.endswith(".incomplete") for p in self.dst.iterdir()))
        # a leftover partial snapshot from a crashed run is cleaned by the next rotation
        (self.dst / "2099-01-01T000000.incomplete").mkdir()
        time.sleep(1.1)
        self.run_job(j)
        names = sorted(p.name for p in self.dst.iterdir())
        self.assertNotIn("2099-01-01T000000.incomplete", names)
        self.assertIn(good[0], names)


class TwoWayTest(RunnerTestBase):
    def tw(self, **kw) -> SyncJob:
        j = self.job(mode=Mode.TWO_WAY)
        for k, v in kw.items():
            setattr(j.twoway, k, v)
        return j

    def test_merge_then_propagate_both_ways_with_trash(self) -> None:
        write(self.src / "a.txt", "A")
        write(self.dst / "b.txt", "B")
        j = self.tw()
        run = self.run_job(j)
        self.assertEqual(run.status, RunStatus.SUCCESS, run.message + run.fix)
        self.assertTrue((self.dst / "a.txt").exists() and (self.src / "b.txt").exists())
        # change on B, delete on A
        write(self.dst / "b.txt", "B2", mtime=time.time() + 5)
        (self.src / "a.txt").unlink()
        run = self.run_job(j)
        self.assertEqual(run.status, RunStatus.SUCCESS, run.message + run.fix)
        self.assertEqual((self.src / "b.txt").read_text(), "B2")
        self.assertFalse((self.dst / "a.txt").exists())
        trashed = list((self.dst / ".lfc-trash").rglob("a.txt"))
        self.assertEqual(len(trashed), 1)
        # overwritten old version of b.txt kept in the source-side trash
        self.assertTrue(list((self.src / ".lfc-trash").rglob("b.txt")))

    def test_conflict_keep_both(self) -> None:
        write(self.src / "todo.md", "base")
        j = self.tw(conflict=ConflictPolicy.KEEP_BOTH)
        self.run_job(j)
        now = time.time()
        write(self.src / "todo.md", "mine", mtime=now + 10)
        write(self.dst / "todo.md", "theirs-newer", mtime=now + 20)
        preview = self.run_job(j, preview=True)
        self.assertEqual([c.kind for c in preview.changes], [ChangeKind.CONFLICT])
        run = self.run_job(j)
        self.assertEqual(run.status, RunStatus.SUCCESS, run.message + run.fix)
        for side in (self.src, self.dst):
            names = sorted(p.name for p in side.iterdir() if not p.name.startswith("."))
            self.assertEqual(len(names), 2, names)
            self.assertEqual((side / "todo.md").read_text(), "theirs-newer")

    def test_ask_policy_stops(self) -> None:
        write(self.src / "f.txt", "base")
        j = self.tw(conflict=ConflictPolicy.ASK)
        self.run_job(j)
        write(self.src / "f.txt", "one", mtime=time.time() + 10)
        write(self.dst / "f.txt", "two!", mtime=time.time() + 20)
        run = self.run_job(j)
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual((self.src / "f.txt").read_text(), "one")

    def test_delete_guard(self) -> None:
        for i in range(20):
            write(self.src / f"f{i}.txt", str(i))
        j = self.tw(delete_guard_percent=50)
        self.run_job(j)
        for i in range(15):
            (self.dst / f"f{i}.txt").unlink()
        run = self.run_job(j)
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertIn("deleted", run.message)
        self.assertEqual(len(list(self.src.glob("f*.txt"))), 20)

    def test_emptied_side_stops_instead_of_deleting(self) -> None:
        for i in range(3):
            write(self.src / f"f{i}.txt", str(i))
        j = self.tw()
        self.run_job(j)
        for p in self.dst.iterdir():
            if p.is_file():
                p.unlink()
        run = self.run_job(j)
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertIn("missing or empty", run.message)
        self.assertEqual(len(list(self.src.glob("f*.txt"))), 3)

    @unittest.skipIf(os.geteuid() == 0, "root can read everything")
    def test_unreadable_folder_is_not_treated_as_deleted(self) -> None:
        for i in range(12):
            write(self.src / f"f{i}.txt", str(i))
        write(self.src / "secret" / "s1", "keep me")
        j = self.tw()
        self.run_job(j)
        os.chmod(self.dst / "secret", 0)
        try:
            run = self.run_job(j)
        finally:
            os.chmod(self.dst / "secret", 0o755)
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual((self.src / "secret" / "s1").read_text(), "keep me")

    def test_names_starting_with_hash_are_copied(self) -> None:
        write(self.src / "#notes.txt", "a")
        write(self.src / ";odd", "b")
        run = self.run_job(self.tw())
        self.assertEqual(run.status, RunStatus.SUCCESS, run.message)
        self.assertTrue((self.dst / "#notes.txt").exists() and (self.dst / ";odd").exists())

    def test_folder_deletion_propagates(self) -> None:
        write(self.src / "d" / "x.txt", "x")
        write(self.src / "keep.txt", "k")
        j = self.tw()
        self.run_job(j)
        import shutil as _sh
        _sh.rmtree(self.dst / "d")
        run = self.run_job(j)
        self.assertEqual(run.status, RunStatus.SUCCESS, run.message + run.fix)
        self.assertFalse((self.src / "d").exists())
        self.assertTrue(list((self.src / ".lfc-trash").rglob("x.txt")))


class ManagerTest(RunnerTestBase):
    def test_same_destination_is_queued(self) -> None:
        write(self.src / "big.bin", "z" * 400_000)
        a = self.job()
        a.performance.limit_speed, a.performance.speed_limit = True, 0.2   # MB/s
        b = self.job()
        b.name = "second"
        b.ensure_identity()
        b.id = "second-0001"
        mgr = RunManager(self.services)
        ra = mgr.start(a)
        rb = mgr.start(b)
        self.assertEqual(rb.status, RunStatus.QUEUED)
        self.assertIs(mgr.start(a), ra)       # same job not started twice
        ra.join(30)
        deadline = time.time() + 20
        while rb.active and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual(rb.status, RunStatus.SUCCESS, rb.message)


if __name__ == "__main__":
    unittest.main()


class DriveTriggerTest(unittest.TestCase):
    """The drive trigger fires on plug-in only, not on mount/unmount of a present drive."""

    def test_plug_in_vs_mount(self) -> None:
        import gi

        gi.require_version("Gtk", "3.0")
        from linfilecopy.engine.drives import DriveInfo
        from linfilecopy.model.enums import DriveKind
        from linfilecopy.model.job import SyncJob
        from linfilecopy.ui import manager_triggers as mt

        job = SyncJob(name="t", id="t-0001")
        job.destination.volume_uuid = "STICK"
        job.triggers.on_drive_connected = True
        started: list[str] = []

        class Store:
            def list(self):
                return [job]

        class Ctx:
            jobs = Store()

            def subscribe(self, *_a):
                pass

        mgr = mt.TriggerManager.__new__(mt.TriggerManager)
        mgr.ctx, mgr.watchers, mgr._mounted = Ctx(), {}, None
        orig = mt.GLib.timeout_add
        mt.GLib.timeout_add = lambda _ms, fn, j: started.append(j.id)
        try:
            unmounted = DriveInfo("/b/sdb1", "/dev/sdb1", "STICK", "Stick", "exfat", 1, (), DriveKind.REMOVABLE)
            mounted = DriveInfo("/b/sdb1", "/dev/sdb1", "STICK", "Stick", "exfat", 1, ("/media/x",), DriveKind.REMOVABLE)
            mgr._on_drives([mounted])           # start-up: present
            mgr._on_drives([unmounted])         # our run unmounted it
            mgr._on_drives([mounted])           # our run mounted it again
            self.assertEqual(started, [])
            mgr._on_drives([])                  # unplugged
            mgr._on_drives([unmounted])         # plugged in (not yet mounted)
            self.assertEqual(started, ["t-0001"])
        finally:
            mt.GLib.timeout_add = orig
