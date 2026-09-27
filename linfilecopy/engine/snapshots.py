"""Hard-linked snapshot helpers (#17): the ``latest`` link and retention rotation."""
from __future__ import annotations

import datetime as dt
import os
import re
import shutil

SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{6}$")
LATEST = "latest"


def list_snapshots(root: str) -> list[str]:
    """Snapshot folder names under ``root``, oldest first."""
    try:
        names = [e.name for e in os.scandir(root) if e.is_dir(follow_symlinks=False) and SNAPSHOT_RE.match(e.name)]
    except FileNotFoundError:
        return []
    return sorted(names)


INCOMPLETE = ".incomplete"


def finish_snapshot(root: str, name: str) -> None:
    """Rename ``<name>.incomplete`` to ``<name>`` once its copy succeeded."""
    partial = os.path.join(root, name + INCOMPLETE)
    if os.path.isdir(partial):
        os.rename(partial, os.path.join(root, name))


def update_latest(root: str, name: str) -> None:
    """Point ``root/latest`` at ``name`` atomically (relative link, survives remounts)."""
    tmp = os.path.join(root, f".{LATEST}.tmp")
    try:
        os.unlink(tmp)
    except FileNotFoundError:
        pass
    os.symlink(name, tmp)
    os.replace(tmp, os.path.join(root, LATEST))


def _parse(name: str) -> dt.datetime:
    return dt.datetime.strptime(name, "%Y-%m-%dT%H%M%S")


def select_to_remove(names: list[str], keep_daily: int, keep_weekly: int, protect: set[str] | None = None) -> list[str]:
    """Retention: every snapshot from the 24 hours before the newest one, plus the
    newest snapshot of each of the last ``keep_daily`` days and of the last
    ``keep_weekly`` ISO weeks."""
    protect = set(protect or ())
    ordered = sorted((n for n in names if SNAPSHOT_RE.match(n)), reverse=True)  # newest first
    if not ordered:
        return []
    keep: set[str] = {ordered[0]} | protect
    newest = _parse(ordered[0])
    keep |= {n for n in ordered if newest - _parse(n) < dt.timedelta(hours=24)}
    days: list[dt.date] = []
    weeks: list[tuple[int, int]] = []
    for name in ordered:
        when = _parse(name)
        day = when.date()
        week = tuple(when.isocalendar()[:2])
        if day not in days and len(days) < keep_daily:
            days.append(day)
            keep.add(name)
        if week not in weeks and len(weeks) < keep_weekly:
            weeks.append(week)  # type: ignore[arg-type]
            keep.add(name)
    return [n for n in sorted(ordered) if n not in keep]


def rotate(root: str, keep_daily: int, keep_weekly: int) -> list[str]:
    """Delete snapshots outside the retention policy. Returns the removed names."""
    names = list_snapshots(root)
    latest_target = None
    try:
        latest_target = os.readlink(os.path.join(root, LATEST))
    except OSError:
        pass
    removed = select_to_remove(names, keep_daily, keep_weekly, {latest_target} if latest_target else None)
    for name in removed:
        shutil.rmtree(os.path.join(root, name), ignore_errors=False, onerror=_force_writable)
    # Leftovers of failed or cancelled runs (never linked as "latest").
    for entry in os.scandir(root):
        if entry.is_dir(follow_symlinks=False) and entry.name.endswith(INCOMPLETE) and SNAPSHOT_RE.match(entry.name[: -len(INCOMPLETE)]):
            shutil.rmtree(entry.path, onerror=_force_writable)
            removed.append(entry.name)
    return removed


def _force_writable(func, path, _exc) -> None:  # type: ignore[no-untyped-def]
    os.chmod(os.path.dirname(path), 0o700)
    os.chmod(path, 0o700) if not os.path.islink(path) else None
    func(path)
