"""Pure two-way classification (no disk)."""
import datetime as dt
import unittest

from linfilecopy.engine.progress import ChangeKind
from linfilecopy.engine.twoway import Decision, Entry, conflict_name, decide, guard_violation
from linfilecopy.model.enums import ConflictPolicy

F = lambda size, t: Entry(False, size, t * 10**9)  # noqa: E731
D = Entry(True, 0, 0)
NOW = dt.datetime(2026, 9, 27, 12, 0, 0)


def run(a, b, s, policy=ConflictPolicy.NEWER) -> Decision:
    return decide(a, b, s, policy, 1000, NOW, "host")


class DecideTest(unittest.TestCase):
    def test_first_run_merges(self) -> None:
        d = run({"a": F(1, 1)}, {"b": F(1, 1)}, None)
        self.assertEqual((d.copy_a_to_b, d.copy_b_to_a), (["a"], ["b"]))

    def test_one_side_changed(self) -> None:
        s = {"f": F(1, 1)}
        self.assertEqual(run({"f": F(2, 5)}, {"f": F(1, 1)}, s).copy_a_to_b, ["f"])
        self.assertEqual(run({"f": F(1, 1)}, {"f": F(3, 9)}, s).copy_b_to_a, ["f"])

    def test_both_changed_same_content_is_fine(self) -> None:
        d = run({"f": F(2, 5)}, {"f": F(2, 5)}, {"f": F(1, 1)})
        self.assertTrue(d.empty)

    def test_deletions(self) -> None:
        s = {"f": F(1, 1), "g": F(1, 1)}
        d = run({"f": F(1, 1)}, {"g": F(1, 1)}, s)
        self.assertEqual((d.delete_a, d.delete_b), (["f"], ["g"]))

    def test_deleted_but_changed_elsewhere_is_restored(self) -> None:
        d = run({"f": F(9, 9)}, {}, {"f": F(1, 1)})
        self.assertEqual(d.copy_a_to_b, ["f"])
        self.assertEqual(d.delete_a, [])

    def test_conflict_policies(self) -> None:
        a, b, s = {"f": F(10, 5)}, {"f": F(20, 3)}, {"f": F(1, 1)}
        self.assertEqual(run(a, b, s, ConflictPolicy.NEWER).copy_a_to_b, ["f"])
        self.assertEqual(run(a, b, s, ConflictPolicy.LARGER).copy_b_to_a, ["f"])
        self.assertEqual(run(a, b, s, ConflictPolicy.SOURCE).copy_a_to_b, ["f"])
        ask = run(a, b, s, ConflictPolicy.ASK)
        self.assertEqual(ask.unresolved, ["f"])
        self.assertFalse(ask.copy_a_to_b or ask.copy_b_to_a)
        both = run(a, b, s, ConflictPolicy.KEEP_BOTH)
        self.assertEqual(both.rename_b, {"f": "f.conflict-host-2026-09-27-120000"})
        kinds = [c.kind for c in both.changes(a, b)]
        self.assertEqual(kinds, [ChangeKind.CONFLICT])

    def test_folder_deleted_only_when_empty_after(self) -> None:
        s = {"d": D, "d/x": F(1, 1)}
        d = run({"d": D, "d/x": F(1, 1), "d/new": F(1, 5)}, {}, s)
        self.assertNotIn("d", d.delete_a)       # new file inside survives
        self.assertIn("d/x", d.delete_a)
        d2 = run({"d": D, "d/x": F(1, 1)}, {}, s)
        self.assertEqual(sorted(d2.delete_a), ["d", "d/x"])

    def test_file_vs_folder_is_unresolved(self) -> None:
        d = run({"p": D}, {"p": F(1, 1)}, None)
        self.assertEqual(d.unresolved, ["p"])

    def test_guard(self) -> None:
        a = {f"f{i}": F(1, 1) for i in range(20)}
        d = Decision(delete_a=[f"f{i}" for i in range(15)])
        self.assertIn("15 of 20", guard_violation(d, a, {}, 50))
        self.assertIsNone(guard_violation(Decision(delete_a=["f1"]), a, {}, 50))

    def test_conflict_name_keeps_extension(self) -> None:
        self.assertEqual(conflict_name("notes/todo.md", NOW, "pc"), "notes/todo.conflict-pc-2026-09-27-120000.md")
        self.assertEqual(conflict_name(".bashrc", NOW, "pc"), ".bashrc.conflict-pc-2026-09-27-120000")


if __name__ == "__main__":
    unittest.main()
