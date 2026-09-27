#!/usr/bin/env python3
"""Seed example jobs, folders and run history for screenshots and manual testing.

Everything is created under $LFC_DEMO_DIR (default: a temp folder) and in the
current XDG config/data dirs (tools/screenshot.py points those at a temp
location). Example runs are clearly example data: their log says so.
"""
from __future__ import annotations

import os
import random
import tempfile
import time
from pathlib import Path

from linfilecopy import paths
from linfilecopy.model.enums import ConflictPolicy, Mode, OverwritePolicy, RunStatus, ScheduleKind, Trigger
from linfilecopy.model.history import HistoryStore, RunRecord
from linfilecopy.model.job import SyncJob
from linfilecopy.model.store import JobStore


def _files(root: Path, spec: dict[str, int]) -> None:
    rnd = random.Random(7)
    for rel, size in spec.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(rnd.randbytes(size))


def seed(base: str | None = None) -> dict[str, SyncJob]:
    base_dir = Path(base or os.environ.get("LFC_DEMO_DIR") or tempfile.mkdtemp(prefix="lfc-demo-"))
    docs, music, notes = base_dir / "Documents", base_dir / "Music", base_dir / "Notes"
    _files(docs, {"Projects/linfilecopy/docs/CONCEPT.md": 40_000, "Projects/linfilecopy/tools/icons.manifest": 9_000,
                  "Taxes/2025/return.pdf": 900_000, "Letters/landlord.odt": 30_000, ".cache/thumb.bin": 50_000,
                  "Photos/holiday-01.jpg": 2_400_000, "Photos/holiday-02.jpg": 2_100_000, "notes~": 100,
                  "Videos/talk.mp4": 12_000_000})
    _files(music, {f"Album {a}/track-{t:02d}.flac": 1_500_000 for a in "AB" for t in range(1, 5)})
    _files(notes, {"todo.md": 800, "meetings/2026-09-26.md": 2_000, "ideas/linfilecopy.md": 1_200})
    backup = base_dir / "Backup"
    backup.mkdir(exist_ok=True)

    store = JobStore()
    jobs: dict[str, SyncJob] = {}

    j = SyncJob(name="Documents to USB stick", preview_first=False)
    j.source.path, j.destination.path = str(docs), str(backup / "Documents")
    j.overwrite = OverwritePolicy.NEWER
    jobs["docs"] = store.save(j.ensure_identity())

    j = SyncJob(name="Music → T7 Shield", preview_first=False)
    j.source.path, j.destination.path = str(music), str(backup / "Music")
    j.schedule.kind, j.schedule.time, j.schedule.enabled = ScheduleKind.DAILY, "02:00", True
    jobs["music"] = store.save(j.ensure_identity())

    j = SyncJob(name="Home snapshot")
    j.source.path, j.destination.path = str(docs), str(backup / "Snapshots")
    j.safety.snapshots = True
    j.performance.low_priority = True
    j.metadata.acls = j.metadata.xattrs = j.metadata.hardlinks = True
    j.schedule.kind, j.schedule.time, j.schedule.weekdays, j.schedule.enabled = ScheduleKind.WEEKLY, "03:00", [0, 2, 4], True
    jobs["snapshot"] = store.save(j.ensure_identity())

    j = SyncJob(name="Notes two-way")
    j.source.path, j.destination.path = str(notes), str(backup / "Notes")
    j.mode = Mode.TWO_WAY
    j.twoway.conflict = ConflictPolicy.KEEP_BOTH
    j.triggers.on_change = False
    jobs["notes"] = store.save(j.ensure_identity())

    history = HistoryStore()
    now = time.time()
    log_dir = paths.logs_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    examples = [
        (jobs["music"], RunStatus.SUCCESS, now - 3 * 3600, 63, 1_200_000_000, 214, None, "", "", False),
        (jobs["snapshot"], RunStatus.FAILED, now - 9 * 3600, 401, 8_700_000_000, 3112, 23, "Some files could not be copied.",
         "Some files could not be read or written: permission denied. Give your user access, or exclude those folders.", False),
        (jobs["notes"], RunStatus.SUCCESS, now - 26 * 3600, 3, 0, 0, 0, "18 changes found", "", True),
        (jobs["docs"], RunStatus.WARNING, now - 27 * 3600, 860, 2_300_000_000, 9870, 24,
         "Some source files disappeared during the copy.", "Usually harmless: the files changed while copying.", False),
        (jobs["music"], RunStatus.CANCELLED, now - 3 * 86400, 48, 120_000_000, 12, 20, "Cancelled.", "", False),
    ]
    for job, status, started, dur, size, files, code, msg, fix, dry in examples:
        rid = RunRecord.new_id()
        log = log_dir / f"{rid}.log"
        log.write_text(f"(example run created by tools/demo_data.py)\n== Run: {job.name}\n"
                       + ('rsync: [sender] send_files failed to open "/home/sam/Pictures/.private/raw-0113.cr3": Permission denied (13)\n'
                          'rsync error: some files/attrs were not transferred (code 23) at main.c(1338) [sender=3.2.7]\n' if code == 23 else ""))
        history.save(RunRecord(rid, job.id, job.name, started, status, Trigger.SCHEDULE if not dry else Trigger.MANUAL, dry,
                               started + dur, code, size, files, files, 3 if code == 23 else 0, size / max(dur, 1),
                               f"rsync -rlpt ... {job.source.path}/ {job.destination.path}/", "{}", str(log), msg, fix,
                               {"files": files + 40_000 if code == 23 else files, "deleted": 0, "changes": 18 if dry else 0}))
    return jobs


if __name__ == "__main__":
    print(seed())
