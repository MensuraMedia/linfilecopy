"""SyncJob serialisation, migration, identity; templates; JobStore."""
import json
import tempfile
import unittest
from pathlib import Path

from linfilecopy.model.enums import ConflictPolicy, ExcludePreset, FilterAction, Mode, SymlinkPolicy
from linfilecopy.model.job import SCHEMA_VERSION, FilterRule, SyncJob
from linfilecopy.model.store import JobStore
from linfilecopy.model.templates import load_templates


def full_job() -> SyncJob:
    job = SyncJob(name="Everything on")
    job.source.path = "/home/sam/Documents"
    job.destination.path = "/media/sam/B49B-37C5/Documents"
    job.destination.volume_uuid = "B49B-37C5"
    job.mode = Mode.TWO_WAY
    job.filters.rules = [FilterRule(FilterAction.INCLUDE, "Projects/**"), FilterRule(FilterAction.EXCLUDE, "*.iso")]
    job.filters.presets = [ExcludePreset.HIDDEN]
    job.metadata.symlinks = SymlinkPolicy.FOLLOW
    job.twoway.conflict = ConflictPolicy.KEEP_BOTH
    job.schedule.weekdays = [0, 2, 4]
    return job.ensure_identity()


class SyncJobTest(unittest.TestCase):
    def test_round_trip_is_lossless(self) -> None:
        job = full_job()
        data = json.loads(json.dumps(job.to_dict()))
        self.assertEqual(SyncJob.from_dict(data), job)

    def test_enums_serialise_as_strings(self) -> None:
        d = full_job().to_dict()
        self.assertEqual(d["mode"], "two_way")
        self.assertEqual(d["filters"]["rules"][0], {"action": "include", "pattern": "Projects/**"})

    def test_unknown_keys_and_bad_types_fall_back_to_defaults(self) -> None:
        job = SyncJob.from_dict({"name": "x", "mode": "teleport", "bogus": 1,
                                 "performance": {"parallel_streams": "four", "low_priority": "yes"},
                                 "filters": {"presets": ["cache", "nonsense"]}})
        self.assertEqual(job.mode, Mode.COPY)
        self.assertEqual(job.performance.parallel_streams, 1)
        self.assertFalse(job.performance.low_priority)
        self.assertEqual(job.filters.presets, [ExcludePreset.CACHE])

    def test_missing_groups_use_defaults(self) -> None:
        job = SyncJob.from_dict({"name": "min"})
        self.assertTrue(job.transfer.resume)
        self.assertEqual(job.filters.presets, [ExcludePreset.CACHE, ExcludePreset.TEMP])

    def test_v1_migration_drops_network_fields(self) -> None:
        job = SyncJob.from_dict({"schema_version": 1, "name": "old",
                                 "transfer": {"compress": True, "compress_level": 6, "checksum": True},
                                 "destination": {"path": "/x", "host": "nas", "port": 22}})
        self.assertEqual(job.schema_version, SCHEMA_VERSION)
        self.assertTrue(job.transfer.checksum)
        self.assertNotIn("compress", job.to_dict()["transfer"])
        self.assertNotIn("host", job.to_dict()["destination"])

    def test_ids_are_safe_and_unique(self) -> None:
        a = SyncJob(name="Photos → Archive!").ensure_identity()
        b = SyncJob(name="Photos → Archive!").ensure_identity()
        self.assertRegex(a.id, r"^photos-archive-[0-9a-f]{4}$")
        self.assertNotEqual(a.id, b.id)
        self.assertEqual(SyncJob(name="").ensure_identity().id[:4], "job-")

    def test_clone_gets_new_id_and_disables_schedule(self) -> None:
        job = full_job()
        job.schedule.enabled = True
        copy = job.clone("Copy of it")
        self.assertNotEqual(copy.id, job.id)
        self.assertFalse(copy.schedule.enabled)
        self.assertEqual(copy.filters.rules, job.filters.rules)
        copy.filters.rules.clear()
        self.assertEqual(len(job.filters.rules), 2)  # deep copy

    def test_simple_metadata_switch(self) -> None:
        job = SyncJob()
        job.metadata.set_basic(False)
        self.assertFalse(job.metadata.permissions or job.metadata.times)
        self.assertFalse(job.metadata.basic)


class TemplatesTest(unittest.TestCase):
    def test_all_templates_load_in_order(self) -> None:
        keys = [t.key for t in load_templates()]
        self.assertEqual(keys, ["backup-documents", "mirror-to-array", "two-way-usb-stick", "snapshot-backup"])

    def test_instantiate_expands_home_and_sets_identity(self) -> None:
        for t in load_templates():
            job = t.instantiate()
            self.assertTrue(job.id)
            self.assertEqual(job.template, t.key)
            self.assertFalse(job.source.path.startswith("~"), job.source.path)
        snap = next(t for t in load_templates() if t.key == "snapshot-backup").instantiate()
        self.assertTrue(snap.safety.snapshots)


class JobStoreTest(unittest.TestCase):
    def test_save_list_get_delete(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = JobStore(Path(d))
            job = store.save(full_job())
            self.assertTrue(job.modified > 0)
            self.assertEqual([j.id for j in store.list()], [job.id])
            self.assertEqual(store.get(job.id), job)
            store.delete(job.id)
            self.assertIsNone(store.get(job.id))

    def test_corrupt_file_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = JobStore(Path(d))
            store.save(full_job())
            (Path(d) / "broken.json").write_text("{nope")
            self.assertEqual(len(store.list()), 1)

    def test_rejects_path_traversal_ids(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                JobStore(Path(d)).delete("../../etc/passwd")

    def test_import_gets_fresh_id(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = JobStore(Path(d) / "jobs")
            job = full_job()
            f = Path(d) / "exported.json"
            store.export_job(job, f)
            imported = store.import_job(f)
            self.assertNotEqual(imported.id, job.id)
            self.assertEqual(imported.source, job.source)


if __name__ == "__main__":
    unittest.main()
