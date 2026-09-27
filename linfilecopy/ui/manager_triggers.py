"""Automatic runs while the app is open: on file change (#14) and when a drive is plugged in (#19/#20)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib  # noqa: E402

from linfilecopy.engine.drives import DriveInfo  # noqa: E402
from linfilecopy.engine.runner import JobRun  # noqa: E402
from linfilecopy.engine.watcher import FolderWatcher, WatchError  # noqa: E402
from linfilecopy.i18n import _  # noqa: E402
from linfilecopy.log import get_logger  # noqa: E402
from linfilecopy.model.enums import Trigger  # noqa: E402
from linfilecopy.model.job import SyncJob  # noqa: E402
from linfilecopy.ui.context import AppContext  # noqa: E402

_log = get_logger(__name__)
COOLDOWN_S = 5.0          # ignore the job's own writes for a moment after it finishes
DRIVE_SETTLE_MS = 3000    # let the desktop finish mounting before starting


class TriggerManager:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.watchers: dict[str, FolderWatcher] = {}
        self._mounted: set[str] | None = None
        ctx.subscribe("jobs-changed", self.rebuild)
        ctx.subscribe("drives", self._on_drives)
        ctx.subscribe("run-updated", self._on_run)
        ctx.subscribe("run-finished", self._on_run_finished)
        self.rebuild()

    # ----- file change ------------------------------------------------------------------------
    def rebuild(self) -> None:
        jobs = {j.id: j for j in (self.ctx.jobs.list() if self.ctx.jobs else []) if j.triggers.on_change}
        for job_id in list(self.watchers):
            if job_id not in jobs:
                self.watchers.pop(job_id).stop()
        for job_id, job in jobs.items():
            roots = job.triggers.watch_paths or [job.source.path]
            existing = self.watchers.get(job_id)
            if existing is not None and existing.roots == roots and existing.debounce == job.triggers.debounce_seconds:
                continue
            if existing is not None:
                existing.stop()
            watcher = FolderWatcher(roots, lambda job_id=job_id: GLib.idle_add(self._changed, job_id),
                                    job.triggers.debounce_seconds)
            try:
                watcher.start()
                self.watchers[job_id] = watcher
                _log.info("watching %d folders for %s", watcher.watch_count, job.name)
            except WatchError as exc:
                _log.warning("cannot watch %s: %s", roots, exc)

    def _changed(self, job_id: str) -> bool:
        job = self.ctx.jobs.get(job_id) if self.ctx.jobs else None
        if job is None or not job.triggers.on_change or self.ctx.runs is None:
            return GLib.SOURCE_REMOVE
        if self.ctx.runs.active_for_job(job_id) is None:
            self.ctx.runs.start(job, Trigger.FILE_CHANGE)
        return GLib.SOURCE_REMOVE

    def _on_run(self, run: JobRun) -> None:
        watcher = self.watchers.get(run.job.id)
        if watcher is not None and run.active:
            watcher.suppress(COOLDOWN_S)

    def _on_run_finished(self, run: JobRun) -> None:
        watcher = self.watchers.get(run.job.id)
        if watcher is not None:
            watcher.suppress(COOLDOWN_S)

    # ----- drive connected ------------------------------------------------------------------------
    def _on_drives(self, drives: list[DriveInfo]) -> None:
        mounted = {d.uuid for d in drives if d.mounted and d.uuid}
        if self._mounted is None:        # first list after start-up: nothing is "new"
            self._mounted = mounted
            return
        new = mounted - self._mounted
        self._mounted = mounted
        if not new or self.ctx.jobs is None:
            return
        for job in self.ctx.jobs.list():
            if job.triggers.on_drive_connected and {job.source.volume_uuid, job.destination.volume_uuid} & new:
                GLib.timeout_add(DRIVE_SETTLE_MS, self._start_for_drive, job)

    def _start_for_drive(self, job: SyncJob) -> bool:
        if self.ctx.runs is not None and self.ctx.runs.active_for_job(job.id) is None:
            _log.info("drive connected: starting %s", job.name)
            self.ctx.runs.start(job, Trigger.DRIVE_CONNECTED)
            if self.ctx.notifier is not None:
                label = job.destination.volume_label or job.source.volume_label or _("A drive")
                self.ctx.notifier.simple(f"trigger-{job.id}", _("{job} started").format(job=job.name),
                                         _("{drive} was plugged in.").format(drive=label), "trigger-drive")
        return GLib.SOURCE_REMOVE

    def shutdown(self) -> None:
        for w in self.watchers.values():
            w.stop()
        self.watchers.clear()
