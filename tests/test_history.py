import tempfile
import time
import unittest
from pathlib import Path

from linfilecopy.model.enums import RunStatus, Trigger
from linfilecopy.model.history import HistoryStore, RunRecord


def rec(job="j1", status=RunStatus.SUCCESS, started=None, dry=False, **kw) -> RunRecord:
    return RunRecord(RunRecord.new_id(), job, job.upper(), started or time.time(), status, Trigger.MANUAL, dry, **kw)


class HistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = HistoryStore(Path(self.tmp.name) / "h.db")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_save_get_update(self) -> None:
        r = rec(status=RunStatus.RUNNING, command="rsync -a 'a b' /x")
        self.store.save(r)
        r.status, r.exit_code, r.bytes, r.stats = RunStatus.FAILED, 23, 10, {"speed": 1.5}
        self.store.save(r)
        got = self.store.get(r.id)
        self.assertEqual((got.status, got.exit_code, got.bytes, got.stats), (RunStatus.FAILED, 23, 10, {"speed": 1.5}))

    def test_list_filters_and_search_is_parameterised(self) -> None:
        self.store.save(rec("photos", RunStatus.FAILED, message="permission denied"))
        self.store.save(rec("music", RunStatus.SUCCESS))
        self.assertEqual([r.job_id for r in self.store.list(search="permission")], ["photos"])
        self.assertEqual([r.job_id for r in self.store.list(statuses=[RunStatus.SUCCESS])], ["music"])
        self.assertEqual(self.store.list(search="'; DROP TABLE runs; --"), [])
        self.assertEqual(len(self.store.list()), 2)

    def test_totals_ignore_dry_runs(self) -> None:
        self.store.save(rec(bytes=100, files=2))
        self.store.save(rec(bytes=1000, files=20, dry=True))
        self.store.save(rec(status=RunStatus.FAILED, bytes=5, files=1))
        t = self.store.totals_since(0)
        self.assertEqual((t.bytes, t.files, t.runs, t.failed), (105, 3, 2, 1))

    def test_unresolved_failures_only_latest(self) -> None:
        now = time.time()
        self.store.save(rec("a", RunStatus.FAILED, started=now - 100))
        self.store.save(rec("a", RunStatus.SUCCESS, started=now - 10))
        self.store.save(rec("b", RunStatus.FAILED, started=now - 5))
        self.assertEqual([r.job_id for r in self.store.unresolved_failures()], ["b"])

    def test_prune_and_interrupted(self) -> None:
        self.store.save(rec(started=time.time() - 200 * 86400, log_path="/tmp/old.log"))
        self.store.save(rec(status=RunStatus.RUNNING))
        self.assertEqual(self.store.prune(90), ["/tmp/old.log"])
        self.assertEqual(self.store.mark_interrupted(), 1)
        self.assertEqual(self.store.list()[0].status, RunStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
