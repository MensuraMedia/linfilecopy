"""Parsers against output captured from rsync 3.2.7."""
import unittest

from linfilecopy.engine import exitcodes
from linfilecopy.engine.parallel import split_buckets
from linfilecopy.engine.progress import ChangeKind, OutputParser, parse_preview_line, parse_progress
from linfilecopy.model.enums import RunStatus

PROGRESS_OUT = (
    "a.txt\n\r              6   0%    0.00kB/s    0:00:00  \r              6   0%    0.00kB/s    0:00:00 (xfr#1, to-chk=3/5)\n"
    "link -> a.txt\nsub/\nsub/b c.bin\n"
    "\r          5,006  99%    4.77MB/s    0:00:00 (xfr#2, to-chk=0/5)\n\n"
    "Number of files: 5 (reg: 2, dir: 2, link: 1)\nNumber of created files: 3 (reg: 1, dir: 1, link: 1)\n"
    "Number of deleted files: 0\nNumber of regular files transferred: 2\nTotal file size: 5,011 bytes\n"
    "Total transferred file size: 5,006 bytes\nLiteral data: 5,006 bytes\nMatched data: 0 bytes\n"
    "File list size: 0\nTotal bytes sent: 5,211\nTotal bytes received: 56\n\n"
    "sent 5,211 bytes  received 56 bytes  10,534.00 bytes/sec\ntotal size is 5,011  speedup is 0.95\n"
)
PREVIEW_OUT = (
    ">f..t...... 6 a.txt\ncL+++++++++ 5 link -> a.txt\ncd+++++++++ 4096 sub/\n>f+++++++++ 5000 sub/b c.bin\n"
    "*deleting   0 old/gone.txt\n*deleting   0 old/\n.d..t...... 4096 ./\n\nNumber of files: 5 (reg: 2, dir: 2, link: 1)\n"
)


class ProgressTest(unittest.TestCase):
    def test_progress_segment(self) -> None:
        p = parse_progress("     2,528,190,464  62%   38.40MB/s    0:03:12 (xfr#1284, to-chk=766/2050)")
        self.assertEqual(p["bytes_done"], 2_528_190_464)
        self.assertEqual(p["percent"], 62)
        self.assertAlmostEqual(p["speed_bps"], 38.40 * 1024**2)
        self.assertEqual(p["eta_seconds"], 192)
        self.assertEqual((p["files_done"], p["files_total"], p["files_checked"]), (1284, 2050, 1284))
        self.assertIsNone(parse_progress("sub/b c.bin"))

    def test_stream_parser_events_and_stats(self) -> None:
        parser = OutputParser()
        events = list(parser.feed(PROGRESS_OUT[:37])) + list(parser.feed(PROGRESS_OUT[37:])) + list(parser.close())
        files = [p for k, p in events if k == "file"]
        self.assertEqual(files, ["a.txt", "link -> a.txt", "sub/", "sub/b c.bin"])
        self.assertEqual(parser.snapshot.bytes_done, 5006)
        self.assertEqual(parser.snapshot.files_done, 2)
        s = parser.stats
        self.assertEqual((s.files, s.created, s.regular_transferred, s.transferred_size, s.sent), (5, 3, 2, 5006, 5211))

    def test_preview_changes(self) -> None:
        parser = OutputParser(preview=True)
        list(parser.feed(PREVIEW_OUT))
        got = [(c.kind, c.path) for c in parser.changes]
        self.assertEqual(got, [
            (ChangeKind.UPDATE, "a.txt"), (ChangeKind.NEW, "link"), (ChangeKind.NEW, "sub"),
            (ChangeKind.NEW, "sub/b c.bin"), (ChangeKind.DELETE, "old/gone.txt"), (ChangeKind.DELETE, "old"),
        ])
        self.assertEqual(parser.changes[3].size, 5000)
        self.assertEqual(parser.changes[1].link_target, "a.txt")
        self.assertTrue(parser.changes[2].is_dir)

    def test_preview_attrs_only(self) -> None:
        self.assertEqual(parse_preview_line(".f...p..... 10 script.sh").kind, ChangeKind.ATTRS)
        self.assertEqual(parse_preview_line("hf+++++++++ 10 hard").kind, ChangeKind.LINK)
        self.assertIsNone(parse_preview_line("cd+++++++++ 4096 ./"))


class ExitCodeTest(unittest.TestCase):
    def test_known_codes(self) -> None:
        self.assertEqual(exitcodes.explain(0).status, RunStatus.SUCCESS)
        self.assertEqual(exitcodes.explain(24).status, RunStatus.WARNING)
        self.assertEqual(exitcodes.explain(20).status, RunStatus.CANCELLED)
        self.assertTrue(exitcodes.explain(12).transient)
        self.assertFalse(exitcodes.explain(3).transient)
        self.assertIn("99", exitcodes.explain(99).message)

    def test_stderr_refinement(self) -> None:
        full = exitcodes.refine_with_stderr(exitcodes.explain(11), ['rsync: write failed on "/x": No space left on device (28)'])
        self.assertIn("full", full.message)
        self.assertFalse(full.transient)
        perm = exitcodes.refine_with_stderr(exitcodes.explain(23), ['send_files failed to open "/a": Permission denied (13)'])
        self.assertIn("permission denied", perm.fix)


class BucketTest(unittest.TestCase):
    def test_balanced(self) -> None:
        buckets = split_buckets({"a": 100, "b": 60, "c": 50, "d": 10}, 2)
        totals = sorted(sum({"a": 100, "b": 60, "c": 50, "d": 10}[n] for n in b) for b in buckets)
        self.assertEqual(totals, [110, 110])
        self.assertEqual(len(split_buckets({"a": 1}, 4)), 1)


if __name__ == "__main__":
    unittest.main()
