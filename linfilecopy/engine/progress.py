"""Parsers for rsync output (B3, B7, #11). Pure functions over text, fixture-tested.

Formats (verified against rsync 3.2.7, see CONCEPT §6.5):

* progress2:  ``      5,006  99%    4.77MB/s    0:00:00 (xfr#2, to-chk=0/5)``
  (segments separated by ``\\r``; ``name1`` prints each file name on its own line)
* preview:    ``>f+++++++++ 5000 sub/b c.bin`` and ``*deleting   0 old/gone.txt``
  (from ``--itemize-changes --out-format='%i %l %n%L'``)
* stats2:     ``Number of files: 5 (reg: 2, dir: 2, link: 1)`` etc.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator

PROGRESS_RE = re.compile(
    r"^\s*([\d,]+)\s+(\d+)%\s+([\d.,]+)([kKMGT]?B)/s\s+(\d+):(\d{2}):(\d{2})"
    r"(?:\s+\(xfr#(\d+),\s+(?:ir|to)-chk=(\d+)/(\d+)\))?"
)
PREVIEW_RE = re.compile(r"^(\*deleting|[<>ch.*][fdLDS][.+cstpoguaxn ?]{9})\s+(\d+)\s(.*)$")
STAT_RE = re.compile(r"^([A-Z][A-Za-z ]+?):\s+([\d,.]+)")
SENT_RE = re.compile(r"^sent ([\d,]+) bytes\s+received ([\d,]+) bytes\s+([\d,.]+) bytes/sec")
UNIT = {"B": 1, "kB": 1024, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}


def _int(text: str) -> int:
    return int(text.replace(",", "") or 0)


@dataclass
class ProgressSnapshot:
    """Live state of one transfer, updated by :class:`OutputParser`."""

    bytes_done: int = 0
    percent: int = 0
    speed_bps: float = 0.0
    eta_seconds: int | None = None
    files_done: int = 0          # files transferred so far (xfr#)
    files_total: int = 0         # files considered (to-chk total)
    files_checked: int = 0
    current_file: str = ""
    bytes_total_hint: int = 0    # known total (parallel mode, two-way), else estimated from percent
    started: float = field(default_factory=time.time)

    @property
    def elapsed(self) -> float:
        return time.time() - self.started

    @property
    def bytes_total_estimate(self) -> int:
        if self.bytes_total_hint:
            return self.bytes_total_hint
        if self.percent <= 0:
            return 0
        return int(self.bytes_done * 100 / self.percent)

    @property
    def fraction(self) -> float:
        if self.files_total and self.percent >= 99:
            return min(1.0, self.files_checked / self.files_total) if self.files_checked else self.percent / 100
        return self.percent / 100


def parse_progress(line: str) -> dict | None:
    """Parse one progress2 segment into a dict of fields, or None."""
    m = PROGRESS_RE.match(line)
    if not m:
        return None
    number, unit = m.group(3), m.group(4)
    speed = float(number.replace(",", "")) * UNIT.get(unit, UNIT.get(unit.upper(), 1))
    eta = int(m.group(5)) * 3600 + int(m.group(6)) * 60 + int(m.group(7))
    out = {"bytes_done": _int(m.group(1)), "percent": int(m.group(2)), "speed_bps": speed, "eta_seconds": eta}
    if m.group(8):
        remaining, total = int(m.group(9)), int(m.group(10))
        out.update(files_done=int(m.group(8)), files_total=total, files_checked=total - remaining)
    return out


class ChangeKind(Enum):
    NEW = "new"
    UPDATE = "update"
    DELETE = "delete"
    ATTRS = "attrs"         # metadata only
    LINK = "link"           # hard link created
    CONFLICT = "conflict"   # two-way: changed on both sides


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    path: str
    size: int = 0
    is_dir: bool = False
    link_target: str | None = None
    direction: str | None = None    # two-way: "to_destination" | "to_source"
    note: str = ""                  # two-way: how a conflict is resolved


def parse_preview_line(line: str) -> Change | None:
    """Parse one itemised dry-run line; None for anything else (stats, blanks)."""
    m = PREVIEW_RE.match(line.rstrip("\n"))
    if not m:
        return None
    code, size, name = m.group(1), int(m.group(2)), m.group(3)
    target = None
    if " -> " in name and code[1:2] == "L":
        name, target = name.split(" -> ", 1)
    is_dir = name.endswith("/") or code[1:2] == "d"
    path = name.rstrip("/") if name != "/" else name
    if code == "*deleting":
        return Change(ChangeKind.DELETE, path, 0, is_dir)
    if code[0] == "h":
        return Change(ChangeKind.LINK, path, size, is_dir, target)
    if "+++++++++" in code:
        return Change(ChangeKind.NEW, path, size if not is_dir else 0, is_dir, target)
    if code[0] in "<>c" and not is_dir:
        return Change(ChangeKind.UPDATE, path, size, is_dir, target)
    if code[0] == "." and is_dir and code[2:] .strip(".") in ("t", ""):
        return None  # directory timestamp only: noise in a preview
    return Change(ChangeKind.ATTRS, path, 0, is_dir, target)


@dataclass
class TransferStats:
    """Totals from rsync's stats2 block."""

    files: int = 0
    created: int = 0
    deleted: int = 0
    regular_transferred: int = 0
    total_size: int = 0
    transferred_size: int = 0
    literal: int = 0
    matched: int = 0
    sent: int = 0
    received: int = 0
    rate: float = 0.0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


_STAT_KEYS = {
    "Number of files": "files",
    "Number of created files": "created",
    "Number of deleted files": "deleted",
    "Number of regular files transferred": "regular_transferred",
    "Total file size": "total_size",
    "Total transferred file size": "transferred_size",
    "Literal data": "literal",
    "Matched data": "matched",
}


def parse_stats_line(line: str, stats: TransferStats) -> bool:
    """Update ``stats`` from one line. Returns True if the line was a stats line."""
    m = SENT_RE.match(line)
    if m:
        stats.sent, stats.received = _int(m.group(1)), _int(m.group(2))
        stats.rate = float(m.group(3).replace(",", ""))
        return True
    m = STAT_RE.match(line)
    if m and m.group(1) in _STAT_KEYS:
        setattr(stats, _STAT_KEYS[m.group(1)], _int(m.group(2).split(".")[0]))
        return True
    return line.startswith(("total size is", "File list size", "File list generation", "File list transfer",
                            "Total bytes sent", "Total bytes received"))


class OutputParser:
    """Incremental parser for rsync stdout. Feed raw text; iterate events.

    Events: ``("progress", ProgressSnapshot)``, ``("file", name)``,
    ``("change", Change)`` (preview runs), ``("line", text)`` for anything else.
    """

    def __init__(self, preview: bool = False) -> None:
        self.preview = preview
        self.snapshot = ProgressSnapshot()
        self.stats = TransferStats()
        self.changes: list[Change] = []
        self._buffer = ""
        self._in_stats = False

    def feed(self, text: str) -> Iterator[tuple[str, object]]:
        self._buffer += text
        while True:
            idx = min((i for i in (self._buffer.find("\r"), self._buffer.find("\n")) if i >= 0), default=-1)
            if idx < 0:
                break
            segment, self._buffer = self._buffer[:idx], self._buffer[idx + 1:]
            yield from self._segment(segment)

    def close(self) -> Iterator[tuple[str, object]]:
        if self._buffer:
            segment, self._buffer = self._buffer, ""
            yield from self._segment(segment)

    def _segment(self, seg: str) -> Iterator[tuple[str, object]]:
        if not seg.strip():
            return
        if self.preview:
            change = parse_preview_line(seg)
            if change is not None:
                self.changes.append(change)
                yield ("change", change)
                return
        prog = parse_progress(seg)
        if prog is not None:
            for k, v in prog.items():
                setattr(self.snapshot, k, v)
            yield ("progress", self.snapshot)
            return
        if parse_stats_line(seg, self.stats):
            self._in_stats = True
            yield ("line", seg)
            return
        if not self.preview and not self._in_stats and not seg.startswith(("rsync:", "rsync error", "skipping", "created directory")):
            self.snapshot.current_file = seg
            yield ("file", seg)
            return
        yield ("line", seg)
