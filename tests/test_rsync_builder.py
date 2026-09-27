"""Golden tests: every feature's exact rsync options (project rule 6)."""
import unittest

from linfilecopy.engine import rsync_builder as rb
from linfilecopy.engine.filesystems import capabilities_for
from linfilecopy.model.enums import (CompareMethod, ExcludePreset, FilterAction, LogLevel, Mode,
                                     OverwritePolicy, SpeedUnit, SymlinkPolicy)
from linfilecopy.model.job import FilterRule, SyncJob

EXT4 = capabilities_for("ext4")
EXFAT = capabilities_for("exfat")
VFAT = capabilities_for("vfat")
NTFS = capabilities_for("ntfs")
TAIL = [rb.PROGRESS_INFO, "--no-inc-recursive", "--outbuf=L",
        "--exclude=.lfc-trash/", "--exclude=.lfc-stage/", "/src/", "/dst/"]


def job(**kw) -> SyncJob:
    j = SyncJob(name="t")
    j.filters.presets = []
    for k, v in kw.items():
        setattr(j, k, v)
    return j


def argv(j: SyncJob, fs=EXT4, **opts) -> list[str]:
    return rb.build_rsync_argv(j, "/src", "/dst", fs, rb.BuildOptions(**opts))


class BuilderTest(unittest.TestCase):
    def test_default_copy(self) -> None:
        self.assertEqual(argv(job()), ["rsync", "-rlpt", "--partial", "--partial-dir=.lfc-partial", *TAIL])

    def test_b1_copy_folder_itself_drops_trailing_slash(self) -> None:
        j = job(); j.transfer.copy_contents = False
        self.assertEqual(argv(j)[-2:], ["/src", "/dst/"])

    def test_b2_mirror_deletes(self) -> None:
        self.assertIn("--delete-delay", argv(job(mode=Mode.MIRROR)))
        self.assertNotIn("--delete-delay", argv(job(mode=Mode.COPY)))
        self.assertNotIn("--delete-delay", argv(job(mode=Mode.MIRROR), delete=False))

    def test_b5_b3_metadata_flags(self) -> None:
        j = job()
        j.metadata.set_basic(False)
        self.assertEqual(argv(j)[1], "-rl")
        md = j.metadata
        md.permissions = md.times = md.owner = md.group = md.devices = md.acls = md.xattrs = md.hardlinks = True
        self.assertEqual(argv(j)[1], "-rlptgoDAXH")

    def test_b6_presets_after_user_rules(self) -> None:
        j = job()
        j.filters.rules = [FilterRule(FilterAction.INCLUDE, "Projects/**"), FilterRule(FilterAction.EXCLUDE, "*.iso")]
        j.filters.presets = [ExcludePreset.HIDDEN, ExcludePreset.CACHE]
        a = argv(j)
        i = a.index("--include=Projects/**")
        self.assertEqual(a[i:i + 4], ["--include=Projects/**", "--exclude=*.iso", "--exclude=.*", "--exclude=.cache/"])

    def test_5_exclude_from_and_files_from(self) -> None:
        j = job(); j.filters.exclude_from = "/home/x/ex.txt"; j.filters.files_from = "/home/x/list.txt"
        a = argv(j)
        self.assertIn("--exclude-from=/home/x/ex.txt", a)
        self.assertIn("--files-from=/home/x/list.txt", a)
        self.assertIn("--files-from=/tmp/b1", argv(j, files_from="/tmp/b1"))

    def test_b7_4_preview_and_dry_run(self) -> None:
        a = argv(job(), preview=True)
        self.assertIn("--dry-run", a)
        self.assertIn("--itemize-changes", a)
        self.assertIn(f"--out-format={rb.PREVIEW_FORMAT}", a)
        self.assertNotIn(rb.PROGRESS_INFO, a)
        d = argv(job(), dry_run=True)
        self.assertIn("--dry-run", d)
        self.assertIn(rb.PROGRESS_INFO, d)

    def test_b9_overwrite_policies(self) -> None:
        self.assertNotIn("--update", argv(job(overwrite=OverwritePolicy.ALWAYS)))
        self.assertIn("--ignore-existing", argv(job(overwrite=OverwritePolicy.SKIP)))
        self.assertIn("--update", argv(job(overwrite=OverwritePolicy.NEWER)))

    def test_1_delta_and_inplace(self) -> None:
        j = job(); j.transfer.delta = True; j.transfer.inplace = True
        a = argv(j)
        self.assertIn("--no-whole-file", a)
        self.assertIn("--inplace", a)
        self.assertIn("--partial", a)
        self.assertNotIn("--partial-dir=.lfc-partial", a)  # conflicts with --inplace

    def test_2_8_compare_and_checksum(self) -> None:
        j = job(); j.transfer.compare = CompareMethod.SIZE_ONLY
        self.assertIn("--size-only", argv(j))
        j.transfer.checksum = True
        a = argv(j)
        self.assertNotIn("--size-only", a)
        self.assertEqual(a[1], "-rlptc")

    def test_7_resume_off(self) -> None:
        j = job(); j.transfer.resume = False
        self.assertNotIn("--partial", argv(j))

    def test_6_speed_limit(self) -> None:
        j = job(); j.performance.limit_speed = True; j.performance.speed_limit = 20
        self.assertIn("--bwlimit=20480", argv(j))
        j.performance.speed_unit = SpeedUnit.KB; j.performance.speed_limit = 500
        self.assertIn("--bwlimit=500", argv(j))
        j.performance.limit_speed = False
        self.assertFalse(any(x.startswith("--bwlimit") for x in argv(j)))

    def test_6_priority_wrapper(self) -> None:
        a = argv(job(), priority_wrapper=("ionice", "-c3", "nice", "-n19"))
        self.assertEqual(a[:5], ["ionice", "-c3", "nice", "-n19", "rsync"])

    def test_15_sparse(self) -> None:
        j = job(); j.transfer.sparse = True
        self.assertEqual(argv(j)[1], "-rlptS")

    def test_17_link_dest(self) -> None:
        self.assertIn("--link-dest=/dst/latest", argv(job(), link_dest="/dst/latest"))

    def test_18_log_levels(self) -> None:
        j = job(); j.logging.level = LogLevel.VERBOSE
        self.assertIn("-v", argv(j))
        j.logging.level = LogLevel.DEBUG
        self.assertIn("-vv", argv(j))

    def test_symlink_policies(self) -> None:
        j = job(); j.metadata.symlinks = SymlinkPolicy.FOLLOW
        self.assertEqual(argv(j)[1], "-rLpt")
        j.metadata.symlinks = SymlinkPolicy.SKIP
        self.assertEqual(argv(j)[1], "-rpt")


class FilesystemAdaptationTest(unittest.TestCase):
    def rich_job(self) -> SyncJob:
        j = job()
        md = j.metadata
        md.owner = md.group = md.acls = md.xattrs = md.hardlinks = md.devices = True
        return j

    def test_exfat_drops_unsupported_and_widens_time_window(self) -> None:
        a = argv(self.rich_job(), EXFAT)
        self.assertEqual(a[1], "-rt")
        self.assertIn("--modify-window=1", a)

    def test_fat32_same_as_exfat(self) -> None:
        self.assertEqual(argv(self.rich_job(), VFAT)[1:3], ["-rt", "--modify-window=1"])

    def test_ntfs_keeps_links_drops_perms(self) -> None:
        a = argv(self.rich_job(), NTFS)
        self.assertEqual(a[1], "-rltH")
        self.assertNotIn("--modify-window=1", a)

    def test_ext4_keeps_everything(self) -> None:
        self.assertEqual(argv(self.rich_job(), EXT4)[1], "-rlptgoDAXH")

    def test_exfat_follow_links_still_allowed(self) -> None:
        j = job(); j.metadata.symlinks = SymlinkPolicy.FOLLOW
        self.assertEqual(argv(j, EXFAT)[1], "-rLt")


class DisplayTest(unittest.TestCase):
    def test_quoting(self) -> None:
        j = job(); j.filters.rules = [FilterRule(FilterAction.EXCLUDE, "My Files/*")]
        text = rb.display_command(rb.build_rsync_argv(j, "/home/sam/My Docs", "/dst", EXT4))
        self.assertIn("'--exclude=My Files/*'", text)
        self.assertIn("'/home/sam/My Docs/'", text)

    def test_wrapped_display_puts_paths_on_own_lines(self) -> None:
        lines = rb.wrapped_display(argv(job())).splitlines()
        self.assertTrue(lines[-1].strip().startswith("/dst/"))
        self.assertTrue(lines[-2].strip().startswith("/src/"))
        self.assertTrue(all(line.endswith(" \\") for line in lines[:-1]))


if __name__ == "__main__":
    unittest.main()
