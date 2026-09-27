"""Native two-way synchronisation (#13, CONCEPT §6.4).

1. State: the entries both sides had after the last successful sync
   (sqlite per job, keyed to the two roots).
2. Scan both sides with the job's filters.
3. Classify every path against the state (changed on A / B / both, new,
   deleted) and resolve conflicts by the job's policy.
4. Guard against mass deletion (e.g. an empty or wrong drive).
5. Apply: move deletions and overwritten files to ``.lfc-trash/<time>/`` on
   the same side, rename "keep both" losers, then copy each direction with
   rsync ``--files-from`` (so progress, pause and cancel work as usual).
6. Commit the new state only when everything succeeded; an interrupted run
   leaves the old state, so repeating it is safe.
"""
from __future__ import annotations

import datetime as dt
import os
import socket
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable

from linfilecopy import paths
from linfilecopy.engine import rsync_builder as rb
from linfilecopy.engine.filesystems import capabilities_for, fs_type_for_path
from linfilecopy.engine.filtermatch import FilterMatcher
from linfilecopy.engine.progress import Change, ChangeKind
from linfilecopy.i18n import _
from linfilecopy.model.enums import ConflictPolicy, OverwritePolicy
from linfilecopy.model.job import SyncJob

if TYPE_CHECKING:  # pragma: no cover
    from linfilecopy.engine.planner import Step
    from linfilecopy.engine.runner import JobRun

A_TO_B = "to_destination"
B_TO_A = "to_source"
MIN_GUARD_FILES = 10     # the delete guard ignores tiny folders


@dataclass(frozen=True)
class Entry:
    is_dir: bool
    size: int
    mtime_ns: int


Tree = dict[str, Entry]


@dataclass
class Decision:
    copy_a_to_b: list[str] = field(default_factory=list)
    copy_b_to_a: list[str] = field(default_factory=list)
    delete_a: list[str] = field(default_factory=list)
    delete_b: list[str] = field(default_factory=list)
    rename_a: dict[str, str] = field(default_factory=dict)   # keep-both: path -> conflict name (then copied to B)
    rename_b: dict[str, str] = field(default_factory=dict)
    conflicts: list[Change] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)       # policy ASK

    def changes(self, a: Tree, b: Tree) -> list[Change]:
        """Preview rows. Conflicts appear once, with how they will be resolved."""
        in_conflict = {c.path for c in self.conflicts}
        out: list[Change] = []
        for p in self.copy_a_to_b:
            if p in in_conflict:
                continue
            e = a.get(p)
            out.append(Change(ChangeKind.UPDATE if p in b else ChangeKind.NEW, p, e.size if e else 0,
                              bool(e and e.is_dir), direction=A_TO_B))
        for p in self.copy_b_to_a:
            if p in in_conflict:
                continue
            e = b.get(p)
            out.append(Change(ChangeKind.UPDATE if p in a else ChangeKind.NEW, p, e.size if e else 0,
                              bool(e and e.is_dir), direction=B_TO_A))
        out += [Change(ChangeKind.DELETE, p, 0, a[p].is_dir, direction=B_TO_A, note=_("deleted on the other side"))
                for p in self.delete_a if p in a]
        out += [Change(ChangeKind.DELETE, p, 0, b[p].is_dir, direction=A_TO_B, note=_("deleted on the other side"))
                for p in self.delete_b if p in b]
        out += self.conflicts
        return out

    @property
    def empty(self) -> bool:
        return not (self.copy_a_to_b or self.copy_b_to_a or self.delete_a or self.delete_b
                    or self.rename_a or self.rename_b or self.unresolved)


# ---------------------------------------------------------------------------
# scanning

def scan(root: str, matcher: FilterMatcher, check: Callable[[], None] | None = None,
         progress: Callable[[str], None] | None = None) -> Tree:
    """Relative path -> Entry for everything under ``root`` that the filters keep."""
    tree: Tree = {}
    if not os.path.isdir(root):
        return tree
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir
        keep_dirs = []
        for d in dirnames:
            rel = f"{rel_dir}/{d}" if rel_dir else d
            full = os.path.join(dirpath, d)
            if matcher.excluded(rel, True):
                continue
            if os.path.islink(full):
                st = os.lstat(full)
                tree[rel] = Entry(False, st.st_size, st.st_mtime_ns)
                continue
            tree[rel] = Entry(True, 0, 0)
            keep_dirs.append(d)
        dirnames[:] = keep_dirs
        for f in filenames:
            rel = f"{rel_dir}/{f}" if rel_dir else f
            if matcher.excluded(rel, False):
                continue
            try:
                st = os.lstat(os.path.join(dirpath, f))
            except OSError:
                continue
            tree[rel] = Entry(False, st.st_size, st.st_mtime_ns)
        count += 1
        if check and count % 50 == 0:
            check()
        if progress and count % 200 == 0:
            progress(rel_dir)
    return tree


# ---------------------------------------------------------------------------
# state

class StateStore:
    """Last-synced entries for one job, valid only for the same pair of roots."""

    def __init__(self, job_id: str, directory: Path | None = None) -> None:
        directory = directory or paths.twoway_state_dir()
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{job_id}.sqlite"

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, is_dir INT, size INT, mtime_ns INT)")
        return con

    def load(self, signature: str) -> Tree | None:
        """The saved tree, or None on first run / different roots."""
        if not self.path.exists():
            return None
        con = self._connect()
        try:
            row = con.execute("SELECT value FROM meta WHERE key = 'signature'").fetchone()
            if not row or row[0] != signature:
                return None
            return {p: Entry(bool(d), s, m) for p, d, s, m in con.execute("SELECT path, is_dir, size, mtime_ns FROM files")}
        finally:
            con.close()

    def save(self, signature: str, tree: Tree) -> None:
        tmp = self.path.with_suffix(".tmp")
        if tmp.exists():
            tmp.unlink()
        con = sqlite3.connect(tmp)
        try:
            con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            con.execute("CREATE TABLE files (path TEXT PRIMARY KEY, is_dir INT, size INT, mtime_ns INT)")
            con.execute("INSERT INTO meta VALUES ('signature', ?)", (signature,))
            con.execute("INSERT INTO meta VALUES ('saved', ?)", (str(time.time()),))
            con.executemany("INSERT INTO files VALUES (?, ?, ?, ?)",
                            [(p, int(e.is_dir), e.size, e.mtime_ns) for p, e in tree.items()])
            con.commit()
        finally:
            con.close()
        os.replace(tmp, self.path)


def signature(job: SyncJob) -> str:
    """Identifies the pair of roots independent of where the drives are mounted."""
    def side(ep):  # type: ignore[no-untyped-def]
        return f"{ep.volume_uuid}:{ep.relative_path}" if ep.volume_uuid else os.path.normpath(ep.path)
    return f"{side(job.source)}|{side(job.destination)}"


# ---------------------------------------------------------------------------
# decision

def _same(x: Entry, y: Entry, tol_ns: int) -> bool:
    if x.is_dir or y.is_dir:
        return x.is_dir == y.is_dir
    return x.size == y.size and abs(x.mtime_ns - y.mtime_ns) <= tol_ns


def conflict_name(path: str, when: dt.datetime | None = None, host: str | None = None) -> str:
    when = when or dt.datetime.now()
    host = host or socket.gethostname().split(".")[0]
    head, tail = os.path.split(path)
    stem, ext = os.path.splitext(tail)
    if stem.startswith(".") and not ext:
        stem, ext = tail, ""
    return os.path.join(head, f"{stem}.conflict-{host}-{when:%Y-%m-%d-%H%M%S}{ext}")


def decide(a: Tree, b: Tree, state: Tree | None, policy: ConflictPolicy, tol_ns: int,
           now: dt.datetime | None = None, host: str | None = None) -> Decision:
    """Pure classification of both trees against the last-synced state."""
    s = state or {}
    d = Decision()

    def conflict(p: str) -> None:
        x, y = a[p], b[p]
        if policy is ConflictPolicy.ASK:
            d.unresolved.append(p)
            d.conflicts.append(Change(ChangeKind.CONFLICT, p, max(x.size, y.size), note=_("changed on both sides")))
            return
        if policy is ConflictPolicy.SOURCE:
            a_wins = True
        elif policy is ConflictPolicy.LARGER:
            a_wins = x.size >= y.size if x.size != y.size else x.mtime_ns >= y.mtime_ns
        else:  # NEWER and KEEP_BOTH pick the newer copy as the live one
            a_wins = x.mtime_ns >= y.mtime_ns
        if policy is ConflictPolicy.KEEP_BOTH:
            loser_name = conflict_name(p, now, host)
            if a_wins:
                d.rename_b[p] = loser_name
                d.copy_a_to_b.append(p)
                note = _("destination copy kept as {name}").format(name=os.path.basename(loser_name))
            else:
                d.rename_a[p] = loser_name
                d.copy_b_to_a.append(p)
                note = _("source copy kept as {name}").format(name=os.path.basename(loser_name))
        else:
            (d.copy_a_to_b if a_wins else d.copy_b_to_a).append(p)
            note = _("source copy wins") if a_wins else _("destination copy wins")
        d.conflicts.append(Change(ChangeKind.CONFLICT, p, max(x.size, y.size),
                                  direction=A_TO_B if a_wins else B_TO_A, note=note))

    for p in sorted(set(a) | set(b) | set(s)):
        x, y, z = a.get(p), b.get(p), s.get(p)
        if x and y:
            if x.is_dir and y.is_dir:
                continue
            if x.is_dir != y.is_dir:
                d.unresolved.append(p)
                d.conflicts.append(Change(ChangeKind.CONFLICT, p, note=_("a folder on one side, a file on the other")))
                continue
            if _same(x, y, tol_ns):
                continue
            if z is None:
                conflict(p)                 # new on both sides and different
                continue
            ca, cb = not _same(x, z, tol_ns), not _same(y, z, tol_ns)
            if ca and not cb:
                d.copy_a_to_b.append(p)
            elif cb and not ca:
                d.copy_b_to_a.append(p)
            else:
                conflict(p)
        elif x and not y:
            if z is None:
                d.copy_a_to_b.append(p)     # new on A
            elif x.is_dir or _same(x, z, tol_ns):
                d.delete_a.append(p)        # deleted on B, untouched on A
            else:
                d.copy_a_to_b.append(p)     # deleted on B but changed on A: keep the change
        elif y and not x:
            if z is None:
                d.copy_b_to_a.append(p)
            elif y.is_dir or _same(y, z, tol_ns):
                d.delete_b.append(p)
            else:
                d.copy_b_to_a.append(p)

    # A folder is only deleted when nothing inside it survives on that side.
    def prune_dirs(deletes: list[str], tree: Tree, copies_into: list[str]) -> list[str]:
        doomed = set(deletes)
        keep = []
        for p in deletes:
            if tree.get(p) and tree[p].is_dir:
                prefix = p + "/"
                survivors = [q for q in tree if q.startswith(prefix) and q not in doomed]
                incoming = [q for q in copies_into if q.startswith(prefix)]
                if survivors or incoming:
                    continue
            keep.append(p)
        return keep

    d.delete_a = prune_dirs(d.delete_a, a, d.copy_b_to_a)
    d.delete_b = prune_dirs(d.delete_b, b, d.copy_a_to_b)
    return d


def guard_violation(d: Decision, a: Tree, b: Tree, percent: int) -> str | None:
    """Message when deletions exceed the guard on either side."""
    for deletes, tree, side in ((d.delete_a, a, _("source")), (d.delete_b, b, _("destination"))):
        files = [p for p in deletes if p in tree and not tree[p].is_dir]
        total = sum(1 for e in tree.values() if not e.is_dir)
        if len(files) >= MIN_GUARD_FILES and total and len(files) * 100 / total > percent:
            return _("{n} of {total} files would be deleted on the {side} side ({pct}% — more than the {limit}% limit).").format(
                n=len(files), total=total, side=side, pct=round(len(files) * 100 / total), limit=percent)
    return None


# ---------------------------------------------------------------------------
# applying

def _to_trash(root: str, rel: str, stamp: str, use_trash: bool) -> None:
    src = os.path.join(root, rel)
    if not os.path.lexists(src):
        return
    if not use_trash:
        if os.path.isdir(src) and not os.path.islink(src):
            os.rmdir(src) if not os.listdir(src) else None
        else:
            os.unlink(src)
        return
    dst = os.path.join(root, rb.TRASH_DIR, stamp, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.rename(src, dst)


def _rsync_argv(job: SyncJob, src_root: str, dst_root: str, list_file: str, trash_stamp: str | None,
                wrapper: tuple[str, ...], rsync_path: str) -> list[str]:
    """Copy exactly the listed paths (no recursion), backing up anything replaced."""
    eff = SyncJob.from_dict(job.to_dict())
    eff.overwrite = OverwritePolicy.ALWAYS
    eff.filters.presets, eff.filters.rules, eff.filters.exclude_from = [], [], None
    fs = capabilities_for(fs_type_for_path(dst_root))
    argv = rb.build_rsync_argv(eff, src_root, dst_root, fs,
                               rb.BuildOptions(files_from=list_file, priority_wrapper=wrapper, rsync_path=rsync_path))
    flag_i = next(i for i, a in enumerate(argv) if a.startswith("-") and not a.startswith("--") and a.startswith("-r"))
    argv[flag_i] = "-d" + argv[flag_i][2:]            # listed dirs are created, not recursed
    argv = [a for a in argv if not a.startswith("--exclude=")]
    # The decision is already made: copy every listed file even when rsync's
    # whole-second quick check would call it unchanged.
    argv.insert(flag_i + 1, "--ignore-times")
    if trash_stamp:
        argv[flag_i + 1:flag_i + 1] = ["--backup", f"--backup-dir={rb.TRASH_DIR}/{trash_stamp}"]
    return argv


def _with_parents(paths_: Iterable[str]) -> list[str]:
    out: set[str] = set()
    for p in paths_:
        out.add(p)
        parent = os.path.dirname(p)
        while parent:
            out.add(parent)
            parent = os.path.dirname(parent)
    return sorted(out)


def run_twoway(run: "JobRun", step: "Step") -> None:
    from linfilecopy.engine.runner import StepFailed

    job = run.job
    root_a, root_b = step.params["source"], step.params["destination"]
    preview = bool(step.params.get("preview"))
    matcher = FilterMatcher.for_job(job)
    coarse = capabilities_for(fs_type_for_path(root_b)).coarse_times or capabilities_for(fs_type_for_path(root_a)).coarse_times
    tol_ns = 2_000_000_000 if coarse else 1_000

    def scanning(side: str) -> Callable[[str], None]:
        def cb(rel: str) -> None:
            run.snapshot.current_file = f"{side}: {rel}"
            run._notify()
        return cb

    run.step_description = _("Comparing both sides…")
    run._notify(force=True)
    if not os.path.isdir(root_b) and not preview:
        os.makedirs(root_b, exist_ok=True)
    tree_a = scan(root_a, matcher, run._check_cancel, scanning(_("source")))
    tree_b = scan(root_b, matcher, run._check_cancel, scanning(_("destination")))
    store = StateStore(job.id)
    sig = signature(job)
    state = store.load(sig)
    if state is None:
        run.log(_("First two-way run for these folders: both sides are merged."))
    decision = decide(tree_a, tree_b, state, job.twoway.conflict, tol_ns)
    run.changes = decision.changes(tree_a, tree_b)
    run.snapshot.files_total = len(decision.copy_a_to_b) + len(decision.copy_b_to_a)
    run.snapshot.bytes_total_hint = sum(tree_a[p].size for p in decision.copy_a_to_b if p in tree_a) + \
        sum(tree_b[p].size for p in decision.copy_b_to_a if p in tree_b)

    if preview:
        return
    guard = guard_violation(decision, tree_a, tree_b, job.twoway.delete_guard_percent)
    if guard:
        raise StepFailed(guard, _("Check that the right drive is connected. If the deletions are intended, raise the limit in Settings."))
    if decision.unresolved:
        raise StepFailed(_("{n} files changed on both sides and need your decision.").format(n=len(decision.unresolved)),
                         _("Open Preview to see them, then choose a conflict policy other than \"Ask\"."))
    if decision.empty:
        run.log(_("Both sides are already in step."))
        store.save(sig, {p: e for p, e in tree_a.items() if p in tree_b and _same(e, tree_b[p], tol_ns)})
        return

    stamp = dt.datetime.now().strftime("%Y-%m-%dT%H%M%S")
    use_trash = job.twoway.use_trash
    try:
        for rel in sorted(decision.delete_a, key=len, reverse=True):
            _to_trash(root_a, rel, stamp, use_trash)
        for rel in sorted(decision.delete_b, key=len, reverse=True):
            _to_trash(root_b, rel, stamp, use_trash)
        for rel, new in decision.rename_a.items():
            os.rename(os.path.join(root_a, rel), os.path.join(root_a, new))
            decision.copy_a_to_b.append(new)
        for rel, new in decision.rename_b.items():
            os.rename(os.path.join(root_b, rel), os.path.join(root_b, new))
            decision.copy_b_to_a.append(new)
    except OSError as exc:
        raise StepFailed(_("Could not move a file aside: {err}").format(err=exc), _("Check permissions on both folders.")) from exc

    caps = run.services.capabilities
    rsync_path = caps.rsync.path if caps and caps.rsync.path else "rsync"
    wrapper: tuple[str, ...] = ()
    if job.performance.low_priority and caps:
        wrapper = (("ionice", "-c3") if caps.ionice.available else ()) + (("nice", "-n19") if caps.nice.available else ())
    with tempfile.TemporaryDirectory(prefix="lfc-2way-") as tmp:
        for items, src, dst, label in ((decision.copy_a_to_b, root_a, root_b, _("Copying to the destination")),
                                       (decision.copy_b_to_a, root_b, root_a, _("Copying to the source"))):
            if not items:
                continue
            list_file = os.path.join(tmp, "list.txt")
            with open(list_file, "w", encoding="utf-8") as fh:
                fh.write("\n".join(_with_parents(items)) + "\n")
            run.step_description = label
            run._notify(force=True)
            code = run.run_rsync(_rsync_argv(job, src, dst, list_file, stamp if use_trash else None, wrapper, rsync_path))
            run.exit_code = code
            if code not in (0, 24):
                from linfilecopy.engine import exitcodes

                info = exitcodes.refine_with_stderr(exitcodes.explain(code), run.errors)
                raise StepFailed(info.message, info.fix, code)

    run.step_description = _("Saving sync state")
    run._notify(force=True)
    final_a = scan(root_a, matcher, run._check_cancel)
    final_b = scan(root_b, matcher, run._check_cancel)
    store.save(sig, {p: e for p, e in final_a.items() if p in final_b and _same(e, final_b[p], tol_ns)})
