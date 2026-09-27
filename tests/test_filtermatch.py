"""The Python matcher must agree with real rsync on the patterns the UI produces."""
import os
import shutil
import subprocess
import tempfile
import unittest

from linfilecopy.engine.filtermatch import FilterMatcher

TREE = [
    "a.txt", "b.iso", ".hidden", ".cache/x.bin", "docs/readme.md", "docs/.git/config", "docs/sub/deep.iso",
    "Projects/p1/main.py", "Projects/p1/__pycache__/m.pyc", "Downloads/big.iso", "notes~", "My Files/x y.txt",
    "node_modules/pkg/index.js", "src/node_modules/lib.js", "lost+found/f", "photo.JPG", "a/b/c/d.txt",
]
CASES = [
    [(False, "*.iso")],
    [(False, ".*")],
    [(True, "Projects/**"), (False, "*.iso"), (False, ".*")],
    [(False, "docs/")],
    [(False, "/docs")],
    [(False, "sub/")],
    [(False, "node_modules/"), (False, "__pycache__/"), (False, "*~")],
    [(False, "Downloads/")],
    [(False, "My Files/*")],
    [(False, "*.[Jj][Pp][Gg]")],
    [(False, "a/**/d.txt")],
    [(False, "b/c")],
    [(True, "docs/***"), (False, "*")],
    [(False, "?.txt")],
]


def rsync_listing(root: str, rules: list[tuple[bool, str]]) -> set[str]:
    args = ["rsync", "-r", "--list-only"]
    args += [f"--{'include' if inc else 'exclude'}={p}" for inc, p in rules]
    out = subprocess.run(args + [root + "/"], capture_output=True, text=True, check=True).stdout
    paths = set()
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) == 5 and parts[4] != ".":
            paths.add(parts[4])
    return paths


def matcher_listing(root: str, rules: list[tuple[bool, str]]) -> set[str]:
    m = FilterMatcher(rules)
    out = set()
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir
        for d in list(dirnames):
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if m.excluded(rel, True):
                dirnames.remove(d)
            else:
                out.add(rel)
        for f in filenames:
            rel = f"{rel_dir}/{f}" if rel_dir else f
            if not m.excluded(rel, False):
                out.add(rel)
    return out


@unittest.skipUnless(shutil.which("rsync"), "rsync not installed")
class MatchesRsyncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        for rel in TREE:
            p = os.path.join(cls.tmp.name, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").close()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_cases_agree_with_rsync(self) -> None:
        for rules in CASES:
            with self.subTest(rules=rules):
                self.assertEqual(matcher_listing(self.tmp.name, rules), rsync_listing(self.tmp.name, rules))


if __name__ == "__main__":
    unittest.main()
