"""JobStore: one JSON file per job in ``$XDG_CONFIG_HOME/linfilecopy/jobs``."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from linfilecopy import paths
from linfilecopy.log import get_logger
from linfilecopy.model.job import JOB_ID_RE, SyncJob

_log = get_logger(__name__)


class JobStore:
    """Thread-safe load/save/delete of jobs. Writes are atomic (tmp + rename)."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or paths.jobs_dir()
        self._lock = threading.Lock()

    def _path(self, job_id: str) -> Path:
        if not JOB_ID_RE.match(job_id):
            raise ValueError(f"invalid job id: {job_id!r}")
        return self.directory / f"{job_id}.json"

    def list(self) -> list[SyncJob]:
        """All readable jobs, sorted by name. Corrupt files are skipped and logged."""
        jobs: list[SyncJob] = []
        if not self.directory.is_dir():
            return jobs
        for path in self.directory.glob("*.json"):
            try:
                jobs.append(SyncJob.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError, TypeError) as exc:
                _log.warning("skipping unreadable job file %s: %s", path.name, exc)
        jobs.sort(key=lambda j: j.name.lower())
        return jobs

    def get(self, job_id: str) -> SyncJob | None:
        try:
            return SyncJob.from_dict(json.loads(self._path(job_id).read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            _log.warning("cannot read job %s: %s", job_id, exc)
            return None

    def exists(self, job_id: str) -> bool:
        return JOB_ID_RE.match(job_id) is not None and self._path(job_id).is_file()

    def save(self, job: SyncJob) -> SyncJob:
        job.ensure_identity()
        job.modified = time.time()
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self._path(job.id)
            tmp = path.with_suffix(f".tmp{os.getpid()}")
            tmp.write_text(json.dumps(job.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        return job

    def delete(self, job_id: str) -> None:
        with self._lock:
            try:
                self._path(job_id).unlink()
            except FileNotFoundError:
                pass

    def export_job(self, job: SyncJob, target: Path) -> None:
        target.write_text(json.dumps(job.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def import_job(self, source: Path) -> SyncJob:
        """Load a job file from anywhere; it gets a fresh id so nothing is overwritten."""
        job = SyncJob.from_dict(json.loads(source.read_text(encoding="utf-8")))
        job = job.clone(job.name)
        return self.save(job)
