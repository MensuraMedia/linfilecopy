"""HistoryStore: every run with its settings snapshot, command, statistics and result (B8, #11, #18)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from linfilecopy import paths
from linfilecopy.model.enums import RunStatus, Trigger

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    job_id      TEXT NOT NULL,
    job_name    TEXT NOT NULL,
    started     REAL NOT NULL,
    finished    REAL,
    status      TEXT NOT NULL,
    trigger     TEXT NOT NULL,
    dry_run     INTEGER NOT NULL DEFAULT 0,
    exit_code   INTEGER,
    bytes       INTEGER NOT NULL DEFAULT 0,
    files       INTEGER NOT NULL DEFAULT 0,
    files_total INTEGER NOT NULL DEFAULT 0,
    files_failed INTEGER NOT NULL DEFAULT 0,
    avg_speed   REAL NOT NULL DEFAULT 0,
    command     TEXT NOT NULL DEFAULT '',
    job_json    TEXT NOT NULL DEFAULT '{}',
    log_path    TEXT NOT NULL DEFAULT '',
    message     TEXT NOT NULL DEFAULT '',
    fix         TEXT NOT NULL DEFAULT '',
    stats_json  TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS runs_started ON runs(started DESC);
CREATE INDEX IF NOT EXISTS runs_job ON runs(job_id, started DESC);
"""


@dataclass
class RunRecord:
    id: str
    job_id: str
    job_name: str
    started: float
    status: RunStatus
    trigger: Trigger = Trigger.MANUAL
    dry_run: bool = False
    finished: float | None = None
    exit_code: int | None = None
    bytes: int = 0
    files: int = 0
    files_total: int = 0
    files_failed: int = 0
    avg_speed: float = 0.0
    command: str = ""
    job_json: str = "{}"
    log_path: str = ""
    message: str = ""
    fix: str = ""
    stats: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return (self.finished or time.time()) - self.started

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:16]


@dataclass(frozen=True)
class Totals:
    bytes: int
    files: int
    runs: int
    failed: int


_COLUMNS = ("id, job_id, job_name, started, finished, status, trigger, dry_run, exit_code, bytes, files, "
            "files_total, files_failed, avg_speed, command, job_json, log_path, message, fix, stats_json")


def _row_to_record(r: sqlite3.Row) -> RunRecord:
    try:
        stats = json.loads(r["stats_json"] or "{}")
    except ValueError:
        stats = {}
    return RunRecord(
        id=r["id"], job_id=r["job_id"], job_name=r["job_name"], started=r["started"], finished=r["finished"],
        status=RunStatus(r["status"]), trigger=Trigger(r["trigger"]), dry_run=bool(r["dry_run"]),
        exit_code=r["exit_code"], bytes=r["bytes"], files=r["files"], files_total=r["files_total"],
        files_failed=r["files_failed"], avg_speed=r["avg_speed"], command=r["command"], job_json=r["job_json"],
        log_path=r["log_path"], message=r["message"], fix=r["fix"], stats=stats,
    )


class HistoryStore:
    """sqlite-backed run history. Safe to use from worker threads."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.path = db_path or paths.history_db()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            con = sqlite3.connect(self.path, timeout=10)
            con.row_factory = sqlite3.Row
            try:
                yield con
                con.commit()
            finally:
                con.close()

    # ----- writes -------------------------------------------------------------
    def save(self, rec: RunRecord) -> None:
        """Insert or replace a run record."""
        with self._connect() as con:
            con.execute(
                f"INSERT OR REPLACE INTO runs ({_COLUMNS}) VALUES ({', '.join('?' * 20)})",
                (rec.id, rec.job_id, rec.job_name, rec.started, rec.finished, rec.status.value, rec.trigger.value,
                 int(rec.dry_run), rec.exit_code, rec.bytes, rec.files, rec.files_total, rec.files_failed,
                 rec.avg_speed, rec.command, rec.job_json, rec.log_path, rec.message, rec.fix, json.dumps(rec.stats)),
            )

    def prune(self, older_than_days: int) -> list[str]:
        """Delete runs older than N days. Returns their log paths for cleanup."""
        cutoff = time.time() - older_than_days * 86400
        with self._connect() as con:
            logs = [r["log_path"] for r in con.execute("SELECT log_path FROM runs WHERE started < ?", (cutoff,))]
            con.execute("DELETE FROM runs WHERE started < ?", (cutoff,))
        return [p for p in logs if p]

    def mark_interrupted(self) -> int:
        """Runs left 'running' by a crash or power loss become failed."""
        with self._connect() as con:
            cur = con.execute(
                "UPDATE runs SET status = ?, message = ?, finished = COALESCE(finished, started) "
                "WHERE status IN (?, ?, ?, ?)",
                (RunStatus.FAILED.value, "Interrupted: LinFileCopy stopped while this run was active.",
                 RunStatus.RUNNING.value, RunStatus.PAUSED.value, RunStatus.QUEUED.value, RunStatus.WAITING.value),
            )
            return cur.rowcount

    # ----- reads ----------------------------------------------------------------
    def get(self, run_id: str) -> RunRecord | None:
        with self._connect() as con:
            r = con.execute(f"SELECT {_COLUMNS} FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _row_to_record(r) if r else None

    def list(
        self,
        limit: int = 200,
        search: str = "",
        statuses: list[RunStatus] | None = None,
        since: float | None = None,
        job_id: str | None = None,
    ) -> list[RunRecord]:
        where, args = [], []
        if search:
            where.append("(job_name LIKE ? OR command LIKE ? OR message LIKE ?)")
            like = f"%{search}%"
            args += [like, like, like]
        if statuses:
            where.append(f"status IN ({', '.join('?' * len(statuses))})")
            args += [s.value for s in statuses]
        if since is not None:
            where.append("started >= ?")
            args.append(since)
        if job_id:
            where.append("job_id = ?")
            args.append(job_id)
        sql = f"SELECT {_COLUMNS} FROM runs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY started DESC LIMIT ?"
        args.append(limit)
        with self._connect() as con:
            return [_row_to_record(r) for r in con.execute(sql, args)]

    def last_for_job(self, job_id: str, include_dry_run: bool = False) -> RunRecord | None:
        sql = f"SELECT {_COLUMNS} FROM runs WHERE job_id = ?"
        if not include_dry_run:
            sql += " AND dry_run = 0"
        sql += " ORDER BY started DESC LIMIT 1"
        with self._connect() as con:
            r = con.execute(sql, (job_id,)).fetchone()
        return _row_to_record(r) if r else None

    def totals_since(self, since: float) -> Totals:
        with self._connect() as con:
            r = con.execute(
                "SELECT COALESCE(SUM(bytes),0) b, COALESCE(SUM(files),0) f, COUNT(*) n, "
                "COALESCE(SUM(CASE WHEN status = ? THEN 1 ELSE 0 END),0) failed "
                "FROM runs WHERE started >= ? AND dry_run = 0",
                (RunStatus.FAILED.value, since),
            ).fetchone()
        return Totals(int(r["b"]), int(r["f"]), int(r["n"]), int(r["failed"]))

    def unresolved_failures(self) -> list[RunRecord]:
        """Latest run per job where that latest run failed."""
        with self._connect() as con:
            rows = con.execute(
                f"SELECT {_COLUMNS} FROM runs r WHERE dry_run = 0 AND started = "
                "(SELECT MAX(started) FROM runs r2 WHERE r2.job_id = r.job_id AND r2.dry_run = 0) "
                "AND status = ? ORDER BY started DESC",
                (RunStatus.FAILED.value,),
            ).fetchall()
        return [_row_to_record(r) for r in rows]
