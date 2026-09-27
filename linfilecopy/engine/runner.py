"""Job execution (B3, B4, #7, #11, #18).

A :class:`JobRun` executes one plan on a worker thread. rsync runs in its own
process group so Pause/Resume/Cancel (SIGSTOP/SIGCONT/SIGTERM) reach every
child. Callbacks in :class:`RunHooks` are invoked **from the worker thread**;
the UI marshals them to the main loop with ``GLib.idle_add``.

:class:`RunManager` starts runs, queues runs that target the same drive, and
prevents starting a job that is already active.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from linfilecopy import paths
from linfilecopy.engine import exitcodes, planner
from linfilecopy.engine.drives import DriveError, DriveInfo, EndpointState, UDisksClient, find_by_uuid
from linfilecopy.engine.planner import Plan, Step, StepKind
from linfilecopy.engine.progress import Change, OutputParser, ProgressSnapshot, TransferStats
from linfilecopy.engine.tools import Capabilities
from linfilecopy.i18n import _
from linfilecopy.log import get_logger
from linfilecopy.model.enums import RunStatus, Trigger
from linfilecopy.model.history import HistoryStore, RunRecord
from linfilecopy.model.job import SyncJob

_log = get_logger(__name__)
UPDATE_INTERVAL = 0.25          # max 4 UI updates per second
WAIT_POLL_SECONDS = 5.0
MAX_LOG_LINES = 400             # kept in memory for the live log view


class RunCancelled(Exception):
    pass


class StepFailed(Exception):
    def __init__(self, message: str, fix: str = "", code: int | None = None) -> None:
        super().__init__(message)
        self.message, self.fix, self.code = message, fix, code


@dataclass
class RunHooks:
    """Callbacks from the worker thread. All optional."""

    on_update: Callable[["JobRun"], None] | None = None
    on_log: Callable[["JobRun", str], None] | None = None
    on_finished: Callable[["JobRun"], None] | None = None
    # Blocking: return the passphrase for a locked drive, or None to give up.
    request_passphrase: Callable[["JobRun", DriveInfo], "str | None"] | None = None


@dataclass
class EngineServices:
    history: HistoryStore | None = None
    udisks: UDisksClient | None = None
    capabilities: Capabilities | None = None


@dataclass
class JobRun:
    """One execution (or preview) of a job."""

    job: SyncJob
    services: EngineServices
    hooks: RunHooks = field(default_factory=RunHooks)
    trigger: Trigger = Trigger.MANUAL
    dry_run: bool = False
    preview: bool = False
    id: str = field(default_factory=RunRecord.new_id)
    status: RunStatus = RunStatus.QUEUED
    snapshot: ProgressSnapshot = field(default_factory=ProgressSnapshot)
    stats: TransferStats = field(default_factory=TransferStats)
    changes: list[Change] = field(default_factory=list)
    plan: Plan | None = None
    message: str = ""
    fix: str = ""
    exit_code: int | None = None
    step_index: int = 0
    step_description: str = ""
    log_lines: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    finished: float | None = None
    paused_since: float | None = None
    queued_reason: str = ""
    speed_history: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._procs: set[subprocess.Popen] = set()
        self._proc_lock = threading.Lock()
        self._streams: dict[int, tuple[int, int, float]] = {}   # parallel: stream -> (bytes, files, speed)
        self._cancel = threading.Event()
        self._resume = threading.Event()
        self._resume.set()
        self._thread: threading.Thread | None = None
        self._last_update = 0.0
        self._log_fh = None
        self.log_path = str(paths.logs_dir() / f"{self.id}.log")
        self._bytes_before_step = 0
        self._files_before_step = 0

    # ----- control (any thread) --------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._main, name=f"lfc-run-{self.id}", daemon=True)
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    @property
    def active(self) -> bool:
        return not self.status.finished

    def pause(self) -> bool:
        if self.status is not RunStatus.RUNNING:
            return False
        self._resume.clear()
        self._signal(signal.SIGSTOP)
        self.paused_since = time.time()
        self._set_status(RunStatus.PAUSED)
        return True

    def resume(self) -> bool:
        if self.status is not RunStatus.PAUSED:
            return False
        self._signal(signal.SIGCONT)
        self.paused_since = None
        self._resume.set()
        self._set_status(RunStatus.RUNNING)
        return True

    def cancel(self) -> None:
        self._cancel.set()
        self._resume.set()
        with self._proc_lock:
            running = any(p.poll() is None for p in self._procs)
        if running:
            self._signal(signal.SIGTERM)
            self._signal(signal.SIGCONT)   # a stopped process cannot handle SIGTERM
            threading.Timer(5.0, self._signal, (signal.SIGKILL,)).start()
        if self.status is RunStatus.QUEUED:
            self._finish(RunStatus.CANCELLED, _("Removed from the queue."), "")

    def _signal(self, sig: int) -> None:
        with self._proc_lock:
            procs = [p for p in self._procs if p.poll() is None]
        for proc in procs:
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                pass

    # ----- helpers ------------------------------------------------------------
    def _set_status(self, status: RunStatus) -> None:
        self.status = status
        self._save_record()
        self._notify(force=True)

    def _notify(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_update < UPDATE_INTERVAL:
            return
        self._last_update = now
        if self.hooks.on_update:
            self.hooks.on_update(self)

    def log(self, line: str) -> None:
        self.log_lines.append(line)
        if len(self.log_lines) > MAX_LOG_LINES:
            del self.log_lines[: len(self.log_lines) - MAX_LOG_LINES]
        if self._log_fh:
            self._log_fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
        if self.hooks.on_log:
            self.hooks.on_log(self, line)

    def _check_cancel(self) -> None:
        self._resume.wait()
        if self._cancel.is_set():
            raise RunCancelled()

    def _sleep(self, seconds: float) -> None:
        if self._cancel.wait(seconds):
            raise RunCancelled()

    def record(self) -> RunRecord:
        cmd = self.plan.command_text() if self.plan else ""
        return RunRecord(
            id=self.id, job_id=self.job.id, job_name=self.job.name, started=self.started, status=self.status,
            trigger=self.trigger, dry_run=self.dry_run or self.preview, finished=self.finished,
            exit_code=self.exit_code, bytes=self.snapshot.bytes_done, files=self.snapshot.files_done,
            files_total=self.snapshot.files_total, files_failed=len([e for e in self.errors if "failed" in e.lower()]),
            avg_speed=(self.snapshot.bytes_done / max(1e-3, (self.finished or time.time()) - self.started)),
            command=cmd, job_json=json.dumps(self.job.to_dict()), log_path=self.log_path,
            message=self.message, fix=self.fix,
            stats={**self.stats.as_dict(), "changes": len(self.changes)},
        )

    def _save_record(self) -> None:
        if self.services.history is not None:
            try:
                self.services.history.save(self.record())
            except Exception as exc:  # noqa: BLE001 - history must never break a run
                _log.warning("history write failed: %s", exc)

    # ----- main -------------------------------------------------------------------
    def _main(self) -> None:
        try:
            paths.logs_dir().mkdir(parents=True, exist_ok=True)
            self._log_fh = open(self.log_path, "a", encoding="utf-8", buffering=1)
        except OSError as exc:
            _log.warning("cannot open run log: %s", exc)
        self.started = time.time()
        self.snapshot = ProgressSnapshot()
        self._set_status(RunStatus.RUNNING)
        kind = _("Preview") if self.preview else _("Dry run") if self.dry_run else _("Run")
        self.log(f"== {kind}: {self.job.name} ({self.job.id}), trigger={self.trigger.value}")
        try:
            self.plan = self._prepare_plan()
            self._execute(self.plan)
        except RunCancelled:
            self._finish(RunStatus.CANCELLED, _("Cancelled."), "")
        except StepFailed as exc:
            info_status = RunStatus.FAILED
            if exc.code is not None:
                info_status = exitcodes.explain(exc.code).status
            self._finish(info_status, exc.message, exc.fix)
        except Exception as exc:  # noqa: BLE001 - report instead of dying silently
            _log.exception("run %s crashed", self.id)
            self._finish(RunStatus.FAILED, _("Unexpected error: {err}").format(err=exc),
                         _("Open the log and report the problem."))
        else:
            if self.status is RunStatus.RUNNING:
                if self.exit_code == 24:
                    info = exitcodes.explain(24)
                    self._finish(RunStatus.WARNING, info.message, info.fix)
                else:
                    self._finish(RunStatus.SUCCESS, self._success_message(), "")

    def _success_message(self) -> str:
        from linfilecopy.formatting import format_bytes, format_duration

        if self.preview:
            return _("{n} changes found").format(n=len(self.changes))
        return _("{size}, {files} files in {time}").format(
            size=format_bytes(self.snapshot.bytes_done), files=f"{self.snapshot.files_done:,}",
            time=format_duration((self.finished or time.time()) - self.started))

    def _finish(self, status: RunStatus, message: str, fix: str) -> None:
        if self.finished is not None:
            return
        self.finished = time.time()
        self.message, self.fix = message, fix
        self.status = status
        self.log(f"== {status.value}: {message} {fix}".rstrip())
        self._save_record()
        if self._log_fh:
            self._log_fh.close()
            self._log_fh = None
        self._notify(force=True)
        if self.hooks.on_finished:
            self.hooks.on_finished(self)

    # ----- planning ---------------------------------------------------------------
    def _drives(self) -> list[DriveInfo]:
        if self.services.udisks is None:
            return []
        try:
            return self.services.udisks.list_drives()
        except DriveError as exc:
            self.log(f"drive list unavailable: {exc}")
            return []

    def _env(self) -> planner.PlanEnv:
        caps = self.services.capabilities
        return planner.gather_env(
            self.job, self._drives(),
            rsync_path=caps.rsync.path if caps else "rsync",
            rsync_version=caps.rsync_version if caps else (3, 2, 7),
            has_ionice=caps.ionice.available if caps else False,
            has_nice=caps.nice.available if caps else False,
            udisks=self.services.udisks is not None and (caps.udisks.available if caps else True),
        )

    def _prepare_plan(self) -> Plan:
        env = self._env()
        deadline = time.time() + self.job.drive.wait_minutes * 60
        while self.job.drive.wait_for_drive and EndpointState.MISSING in (env.source.state, env.destination.state):
            if time.time() > deadline:
                raise StepFailed(_("The drive was not connected in time."), _("Connect it and run the job again."))
            if self.status is not RunStatus.WAITING:
                self.queued_reason = _("Waiting for the drive to be connected")
                self._set_status(RunStatus.WAITING)
            self._sleep(WAIT_POLL_SECONDS)
            env = self._env()
        if self.status is RunStatus.WAITING:
            self._set_status(RunStatus.RUNNING)

        plan = planner.plan_job(self.job, env, preview=self.preview, dry_run=self.dry_run)
        self._raise_blocking(plan)
        pre = [s for s in plan.steps if s.kind in (StepKind.UNLOCK, StepKind.MOUNT)]
        if pre:
            for s in pre:
                self._check_cancel()
                self._run_step(s)
            env = self._env()
            not_ready = [label for label, res in ((_("source"), env.source), (_("destination"), env.destination))
                         if res.state is not EndpointState.READY]
            if not_ready:
                raise StepFailed(_("The {side} drive is still not available after mounting.").format(side=not_ready[0]),
                                 _("Mount it in your file manager and run the job again."))
            plan = planner.plan_job(self.job, env, preview=self.preview, dry_run=self.dry_run)
            self._raise_blocking(plan)
            plan.steps = [s for s in plan.steps if s.kind not in (StepKind.UNLOCK, StepKind.MOUNT)]
        for issue in plan.issues:
            if issue.level != "info":
                self.log(f"[{issue.level}] {issue.message} {issue.fix}".rstrip())
        return plan

    def _raise_blocking(self, plan: Plan) -> None:
        blocking = [i for i in plan.issues if i.blocking]
        if blocking:
            self.plan = plan
            raise StepFailed(blocking[0].message, blocking[0].fix)

    # ----- execution --------------------------------------------------------------
    def _execute(self, plan: Plan) -> None:
        post_kinds = (StepKind.UNMOUNT, StepKind.LOCK, StepKind.POWER_OFF)
        main = [s for s in plan.steps if s.kind not in post_kinds]
        post = [s for s in plan.steps if s.kind in post_kinds]
        failure: BaseException | None = None
        try:
            for i, step in enumerate(main):
                self._check_cancel()
                self.step_index, self.step_description = i, step.description
                self._notify(force=True)
                self._run_step(step)
        except Exception as exc:  # noqa: BLE001 - includes RunCancelled: still lock the drive below
            failure = exc
        # Always lock/unmount afterwards for safety; only eject after success.
        for step in post:
            if failure is not None and step.kind is StepKind.POWER_OFF:
                continue
            try:
                self._run_step(step)
            except StepFailed as exc:
                self.log(f"{step.description}: {exc.message}")
                if failure is None:
                    self.message = exc.message
            except Exception as exc:  # noqa: BLE001
                self.log(f"{step.description}: {exc}")
        if failure is not None:
            raise failure

    def _run_step(self, step: Step) -> None:
        self.log(f"-- {step.description}")
        handler = {
            StepKind.RSYNC: self._step_rsync,
            StepKind.PARALLEL_RSYNC: self._step_parallel,
            StepKind.TWOWAY: self._step_twoway,
            StepKind.UNLOCK: self._step_unlock,
            StepKind.MOUNT: self._step_mount,
            StepKind.UNMOUNT: self._step_unmount,
            StepKind.LOCK: self._step_lock,
            StepKind.POWER_OFF: self._step_power_off,
            StepKind.HARDLINK_CLONE: self._step_strategy,
            StepKind.SWAP: self._step_strategy,
            StepKind.REMOVE_TREE: self._step_strategy,
            StepKind.UPDATE_LATEST: self._step_strategy,
            StepKind.ROTATE: self._step_strategy,
        }.get(step.kind)
        if handler is None:
            raise StepFailed(_("This step is not supported yet: {step}").format(step=step.description))
        handler(step)

    # rsync --------------------------------------------------------------------------
    def _step_rsync(self, step: Step) -> None:
        assert step.argv is not None
        target = step.params.get("target")
        if target and not (self.preview or self.dry_run):
            # rsync creates only the last folder level. Create the snapshot or
            # staging parent (the job's destination root), but only when its
            # own parent exists, so an unmounted drive is never "created".
            parent = os.path.dirname(target.rstrip("/"))
            if not os.path.isdir(parent) and os.path.isdir(os.path.dirname(parent)):
                os.makedirs(parent, exist_ok=True)
        retries = 0 if (self.preview or self.dry_run) else self.job.logging.retries
        attempt = 0
        while True:
            code = self.run_rsync(step.argv, preview=self.preview)
            self.exit_code = code
            if code in (0, 24):
                return
            info = exitcodes.refine_with_stderr(exitcodes.explain(code), self.errors)
            if self._cancel.is_set():
                raise RunCancelled()
            if info.transient and attempt < retries:
                attempt += 1
                delay = self.job.logging.retry_delay_seconds * (2 ** (attempt - 1))
                self.log(_("Attempt {n} failed ({msg}). Retrying in {s} s.").format(n=attempt, msg=info.message, s=delay))
                self.step_description = _("Retrying in {s} s…").format(s=delay)
                self._notify(force=True)
                self._sleep(delay)
                continue
            raise StepFailed(info.message, info.fix, code)

    def run_rsync(self, argv: list[str], preview: bool = False, stream: int | None = None) -> int:
        """Run one rsync process to completion, streaming progress. Returns its exit code.

        ``stream`` identifies one of several concurrent processes (parallel
        mode); their progress is summed instead of accumulated step by step.
        """
        self._check_cancel()
        self.log("$ " + " ".join(argv))
        env = dict(os.environ)
        env["LC_ALL"] = "C.UTF-8"     # stable output format, UTF-8 file names
        parser = OutputParser(preview=preview)
        base_bytes, base_files = self.snapshot.bytes_done, self.snapshot.files_done
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    start_new_session=True, env=env)
        except FileNotFoundError:
            raise StepFailed(_("rsync was not found."), _("Install rsync, for example: sudo apt install rsync"), 127)
        with self._proc_lock:
            self._procs.add(proc)
        if self.status is RunStatus.PAUSED:   # paused between steps
            self._signal(signal.SIGSTOP)

        def read_stderr() -> None:
            assert proc.stderr is not None
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    self.errors.append(line)
                    self.log(line)

        err_thread = threading.Thread(target=read_stderr, daemon=True)
        err_thread.start()
        assert proc.stdout is not None
        fd = proc.stdout.fileno()
        last_speed_sample = 0.0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            for kind, payload in parser.feed(chunk.decode("utf-8", "replace")):
                if kind == "progress":
                    snap: ProgressSnapshot = payload  # type: ignore[assignment]
                    if stream is None:
                        self.snapshot.percent = snap.percent
                        self.snapshot.speed_bps = snap.speed_bps
                        self.snapshot.eta_seconds = snap.eta_seconds
                        self.snapshot.bytes_done = base_bytes + snap.bytes_done
                        self.snapshot.files_done = base_files + snap.files_done
                        self.snapshot.files_total = max(self.snapshot.files_total, snap.files_total)
                        self.snapshot.files_checked = snap.files_checked
                    else:
                        self._update_stream(stream, snap)
                    now = time.monotonic()
                    if now - last_speed_sample >= 1.0:
                        last_speed_sample = now
                        self.speed_history.append(snap.speed_bps)
                        del self.speed_history[:-60]
                    self._notify()
                elif kind == "file":
                    self.snapshot.current_file = str(payload)
                    if self._log_fh and self.job.logging.level.value != "quiet":
                        self._log_fh.write(f"{payload}\n")
                    self._notify()
                elif kind == "change":
                    self.changes.append(payload)  # type: ignore[arg-type]
                    if len(self.changes) % 200 == 0:
                        self._notify()
                else:
                    self.log(str(payload))
        for kind, payload in parser.close():
            if kind == "change":
                self.changes.append(payload)  # type: ignore[arg-type]
        code = proc.wait()
        err_thread.join(timeout=2)
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()
        with self._proc_lock:
            self._procs.discard(proc)
        if stream is None:
            self._merge_stats(parser.stats)
        else:
            with self._proc_lock:
                self._merge_counts(parser.stats)
        self.log(f"rsync exit code {code}")
        return code

    def _update_stream(self, stream: int, snap: ProgressSnapshot) -> None:
        with self._proc_lock:
            self._streams[stream] = (snap.bytes_done, snap.files_done, snap.speed_bps)
            self.snapshot.bytes_done = sum(v[0] for v in self._streams.values())
            self.snapshot.files_done = sum(v[1] for v in self._streams.values())
            self.snapshot.speed_bps = sum(v[2] for v in self._streams.values())
            total = self.snapshot.bytes_total_hint
            if total:
                self.snapshot.percent = min(99, int(self.snapshot.bytes_done * 100 / total))
                remaining = max(0, total - self.snapshot.bytes_done)
                self.snapshot.eta_seconds = int(remaining / self.snapshot.speed_bps) if self.snapshot.speed_bps else None

    def _merge_counts(self, s: TransferStats) -> None:
        for k, v in s.as_dict().items():
            if isinstance(v, (int, float)) and k != "rate":
                setattr(self.stats, k, getattr(self.stats, k) + v)

    def _merge_stats(self, s: TransferStats) -> None:
        for k, v in s.as_dict().items():
            if isinstance(v, (int, float)) and k != "rate":
                setattr(self.stats, k, getattr(self.stats, k) + v)
        if s.rate:
            self.stats.rate = s.rate
        if s.transferred_size and not self.preview:
            self.snapshot.bytes_done = max(self.snapshot.bytes_done, self.stats.transferred_size)
        if s.regular_transferred:
            self.snapshot.files_done = max(self.snapshot.files_done, self.stats.regular_transferred)
        if s.files:
            self.snapshot.files_total = max(self.snapshot.files_total, self.stats.files)

    # strategies ----------------------------------------------------------------------
    def _step_strategy(self, step: Step) -> None:
        from linfilecopy.engine import atomic, snapshots

        try:
            if step.kind is StepKind.HARDLINK_CLONE:
                atomic.hardlink_clone(step.params["source"], step.params["target"], self._check_cancel)
            elif step.kind is StepKind.SWAP:
                atomic.swap_into_place(step.params["stage"], step.params["target"], step.params["exists"])
            elif step.kind is StepKind.REMOVE_TREE:
                atomic.remove_tree(step.params["path"])
            elif step.kind is StepKind.UPDATE_LATEST:
                snapshots.finish_snapshot(step.params["root"], step.params["name"])
                snapshots.update_latest(step.params["root"], step.params["name"])
            elif step.kind is StepKind.ROTATE:
                removed = snapshots.rotate(step.params["root"], step.params["keep_daily"], step.params["keep_weekly"])
                for name in removed:
                    self.log(_("removed old snapshot {name}").format(name=name))
        except OSError as exc:
            raise StepFailed(_("{step} failed: {err}").format(step=step.description, err=exc.strerror or exc),
                             _("Check free space and permissions on the destination.")) from exc

    def _step_parallel(self, step: Step) -> None:
        from linfilecopy.engine import parallel

        parallel.run_parallel(self, step)

    def _step_twoway(self, step: Step) -> None:
        from linfilecopy.engine import twoway

        twoway.run_twoway(self, step)

    # drives ---------------------------------------------------------------------------
    def _udisks(self) -> UDisksClient:
        if self.services.udisks is None:
            raise StepFailed(_("Drive control is not available (UDisks2 is missing)."),
                             _("Mount the drive in your file manager and run the job again."))
        return self.services.udisks

    def _drive_or_fail(self, uuid: str | None) -> DriveInfo:
        drive = find_by_uuid(self._drives(), uuid or "")
        if drive is None:
            raise StepFailed(_("The drive is not connected."), _("Connect it and run the job again."))
        return drive

    def _step_unlock(self, step: Step) -> None:
        client = self._udisks()
        container = self._drive_or_fail(step.params["container_uuid"])
        if container.locked:
            passphrase = self.hooks.request_passphrase(self, container) if self.hooks.request_passphrase else None
            if not passphrase:
                raise StepFailed(_("{drive} is locked and no passphrase was given.").format(drive=container.label),
                                 _("Unlock it from the sidebar, or save its passphrase in the keyring."))
            try:
                client.unlock(container, passphrase)
            except DriveError as exc:
                raise StepFailed(str(exc), _("Check the passphrase and try again.")) from exc
            finally:
                passphrase = None  # noqa: F841 - drop the reference promptly
        # Mount the cleartext filesystem that appeared.
        for drive in self._drives():
            if drive.container_uuid == container.uuid and not drive.mounted:
                self._mount(client, drive)

    def _step_mount(self, step: Step) -> None:
        drive = self._drive_or_fail(step.params["uuid"])
        if not drive.mounted:
            self._mount(self._udisks(), drive)

    def _mount(self, client: UDisksClient, drive: DriveInfo) -> None:
        try:
            where = client.mount(drive)
            self.log(_("mounted {drive} at {path}").format(drive=drive.label, path=where))
        except DriveError as exc:
            raise StepFailed(str(exc), _("Mount the drive in your file manager and try again.")) from exc

    def _step_unmount(self, step: Step) -> None:
        drive = find_by_uuid(self._drives(), step.params.get("uuid") or "")
        if drive is not None and drive.mounted:
            try:
                os.sync()
                self._udisks().unmount(drive)
            except DriveError as exc:
                raise StepFailed(str(exc), "") from exc

    def _step_lock(self, step: Step) -> None:
        container = find_by_uuid(self._drives(), step.params.get("container_uuid") or "")
        if container is not None and container.encrypted and not container.locked:
            try:
                self._udisks().lock(container.object_path)
            except DriveError as exc:
                raise StepFailed(str(exc), "") from exc

    def _step_power_off(self, step: Step) -> None:
        drives = self._drives()
        drive = find_by_uuid(drives, step.params.get("uuid") or "")
        if drive is None:
            return  # already gone
        try:
            self._udisks().power_off(drive)
            self.log(_("{drive} can now be unplugged.").format(drive=drive.label))
        except DriveError as exc:
            raise StepFailed(str(exc), "") from exc


# ---------------------------------------------------------------------------

def _overlaps(a: SyncJob, b: SyncJob) -> bool:
    """Two jobs should not run at once when they write to the same drive or folder tree."""
    if a.destination.volume_uuid and a.destination.volume_uuid == b.destination.volume_uuid:
        return True
    pa, pb = os.path.normpath(a.destination.path or "/x"), os.path.normpath(b.destination.path or "/y")
    return pa == pb or pa.startswith(pb + os.sep) or pb.startswith(pa + os.sep)


class RunManager:
    """Owns all runs. Listener callbacks come from worker threads (or the caller's thread)."""

    def __init__(self, services: EngineServices, hooks: RunHooks | None = None) -> None:
        self.services = services
        self.hooks = hooks or RunHooks()
        self._runs: dict[str, JobRun] = {}
        self._queue: list[JobRun] = []
        self._lock = threading.RLock()

    def runs(self) -> list[JobRun]:
        with self._lock:
            return list(self._runs.values())

    def active(self) -> list[JobRun]:
        with self._lock:
            return [r for r in self._runs.values() if r.active]

    def get(self, run_id: str) -> JobRun | None:
        return self._runs.get(run_id)

    def active_for_job(self, job_id: str) -> JobRun | None:
        with self._lock:
            return next((r for r in self._runs.values() if r.active and r.job.id == job_id and not r.preview), None)

    def start(self, job: SyncJob, trigger: Trigger = Trigger.MANUAL, dry_run: bool = False,
              preview: bool = False) -> JobRun:
        with self._lock:
            if not preview:
                existing = self.active_for_job(job.id)
                if existing is not None:
                    return existing
            hooks = RunHooks(self.hooks.on_update, self.hooks.on_log, self._on_finished, self.hooks.request_passphrase)
            run = JobRun(job, self.services, hooks, trigger, dry_run, preview)
            self._runs[run.id] = run
            blocker = None
            if not (preview or dry_run):
                blocker = next((r for r in self._runs.values() if r is not run and r.active and not r.preview
                                and not r.dry_run and _overlaps(r.job, job)), None)
            if blocker is not None:
                run.queued_reason = _("Starts when {job} finishes (same destination)").format(job=blocker.job.name)
                run.status = RunStatus.QUEUED
                self._queue.append(run)
                run._save_record()
                if self.hooks.on_update:
                    self.hooks.on_update(run)
            else:
                run.start()
            return run

    def start_now(self, run_id: str) -> None:
        """Start a queued run immediately (user override)."""
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None and run in self._queue:
                self._queue.remove(run)
                run.queued_reason = ""
                run.start()

    def remove_finished(self) -> None:
        with self._lock:
            self._runs = {k: r for k, r in self._runs.items() if r.active}

    def cancel_all(self) -> None:
        for r in self.active():
            r.cancel()

    def pause_all(self) -> None:
        for r in self.active():
            r.pause()

    def _on_finished(self, run: JobRun) -> None:
        if run in self._queue:
            with self._lock:
                self._queue.remove(run)
        if self.hooks.on_finished:
            self.hooks.on_finished(run)
        with self._lock:
            for queued in list(self._queue):
                blocked = any(r.active and r is not queued and r not in self._queue and _overlaps(r.job, queued.job)
                              for r in self._runs.values())
                if not blocked:
                    self._queue.remove(queued)
                    queued.queued_reason = ""
                    queued.start()
