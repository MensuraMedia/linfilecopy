"""SyncJob + environment -> ordered, displayable plan of steps.

The planner is pure: everything it needs about the running system comes in a
:class:`PlanEnv`, which :func:`gather_env` builds (on a worker thread) from
UDisks2, the filesystem and tool detection. The runner executes the steps;
the designer shows :meth:`Plan.display_text` in the command preview.
"""
from __future__ import annotations

import copy
import datetime as dt
import os
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from linfilecopy.engine import rsync_builder as rb
from linfilecopy.engine.drives import DriveInfo, EndpointState, ResolvedEndpoint, resolve_endpoint
from linfilecopy.engine.filesystems import FsCapabilities, capabilities_for, fs_type_for_path
from linfilecopy.i18n import _
from linfilecopy.model.enums import DriveKind, Mode, SymlinkPolicy
from linfilecopy.model.job import SyncJob
from linfilecopy.model.validation import ERROR, INFO, WARNING, Issue, validate_job

SNAPSHOT_FORMAT = "%Y-%m-%dT%H%M%S"
LATEST = "latest"


class StepKind(Enum):
    UNLOCK = "unlock"
    MOUNT = "mount"
    PREFLIGHT = "preflight"
    RSYNC = "rsync"
    PARALLEL_RSYNC = "parallel_rsync"
    HARDLINK_CLONE = "hardlink_clone"
    SWAP = "swap"
    REMOVE_TREE = "remove_tree"
    UPDATE_LATEST = "update_latest"
    ROTATE = "rotate"
    TWOWAY = "twoway"
    UNMOUNT = "unmount"
    LOCK = "lock"
    POWER_OFF = "power_off"


@dataclass
class Step:
    kind: StepKind
    description: str
    argv: list[str] | None = None
    params: dict[str, Any] = field(default_factory=dict)
    # Steps that move data report progress; drive steps are quick bookkeeping.
    @property
    def transfers(self) -> bool:
        return self.kind in (StepKind.RSYNC, StepKind.PARALLEL_RSYNC, StepKind.TWOWAY)


@dataclass
class PlanEnv:
    """Facts about the system at planning time."""

    source: ResolvedEndpoint
    destination: ResolvedEndpoint
    dest_fs: FsCapabilities
    source_exists: bool = True
    dest_exists: bool = True
    latest_snapshot_exists: bool = False
    rsync_path: str | None = "rsync"
    rsync_version: tuple[int, int, int] | None = (3, 2, 7)
    has_ionice: bool = True
    has_nice: bool = True
    udisks: bool = True
    now: dt.datetime = field(default_factory=dt.datetime.now)


@dataclass
class Plan:
    job: SyncJob                   # effective job (after environment adjustments)
    steps: list[Step]
    issues: list[Issue]
    source: str
    destination: str
    adjustments: list[str] = field(default_factory=list)

    @property
    def runnable(self) -> bool:
        return not any(i.blocking for i in self.issues)

    @property
    def main_step(self) -> Step | None:
        return next((s for s in self.steps if s.transfers), None)

    def display_text(self) -> str:
        """Human-readable plan: comments for bookkeeping steps, wrapped rsync commands."""
        if len(self.steps) == 1 and self.steps[0].argv:
            return rb.wrapped_display(self.steps[0].argv)
        lines: list[str] = []
        for n, step in enumerate(self.steps, start=1):
            lines.append(f"# {n}. {step.description}")
            if step.argv:
                lines.append(rb.wrapped_display(step.argv))
        return "\n".join(lines)

    def command_text(self) -> str:
        """What "Copy command" puts on the clipboard."""
        return self.display_text()


def _priority(job: SyncJob, env: PlanEnv) -> tuple[str, ...]:
    if not job.performance.low_priority:
        return ()
    wrapper: tuple[str, ...] = ()
    if env.has_ionice:
        wrapper += ("ionice", "-c3")
    if env.has_nice:
        wrapper += ("nice", "-n19")
    return wrapper


def _adjust_for_environment(job: SyncJob, env: PlanEnv, issues: list[Issue]) -> tuple[SyncJob, list[str]]:
    """Copy of the job with options the destination cannot store removed, plus a note per change."""
    job = copy.deepcopy(job)
    fs = env.dest_fs
    md = job.metadata
    dropped: list[str] = []
    if md.permissions and not fs.permissions:
        dropped.append(_("permissions"))
    if (md.owner or md.group) and not fs.owner:
        dropped.append(_("owners"))
    if md.symlinks is SymlinkPolicy.KEEP and not fs.symlinks:
        dropped.append(_("symbolic links"))
    if md.hardlinks and not fs.hardlinks:
        dropped.append(_("hard links"))
    if (md.acls or md.xattrs) and not fs.acl_xattr:
        dropped.append(_("ACLs and extended attributes"))
    notes: list[str] = []
    if dropped:
        notes.append(_("{fs} can't store {items}, so they are skipped.").format(fs=fs.label, items=", ".join(dropped)))
    if fs.coarse_times and md.times:
        notes.append(_("Dates are kept and compared to within 1 second."))
    if notes:
        issues.append(Issue(INFO, "destination.fs", _("Adjusted for {fs}").format(fs=fs.label), " ".join(notes)))
    if fs.max_file_size:
        issues.append(Issue(WARNING, "destination.fs",
                            _("{fs} cannot hold files larger than 4 GB. Such files will be reported as failed.").format(fs=fs.label),
                            _("Use a drive formatted as exFAT or ext4 for large files.")))

    if (job.safety.snapshots or job.safety.atomic) and not fs.hardlinks:
        issues.append(Issue(ERROR, "safety.snapshots",
                            _("{fs} does not support hard links, which snapshots and atomic replace need.").format(fs=fs.label),
                            _("Turn off snapshots and atomic replace, or use a drive formatted as ext4, Btrfs or XFS.")))
    if job.transfer.sparse and job.transfer.inplace and env.rsync_version and env.rsync_version < (3, 1, 3):
        job.transfer.sparse = False
        issues.append(Issue(WARNING, "transfer.sparse", _("Sparse files with in-place updates need rsync 3.1.3 or newer; sparse handling is off."), ""))
    if job.performance.low_priority and not (env.has_ionice or env.has_nice):
        issues.append(Issue(WARNING, "performance.low_priority", _("ionice and nice are not installed, so background priority has no effect."), ""))
    return job, notes


def _endpoint_issues(job: SyncJob, env: PlanEnv, issues: list[Issue]) -> None:
    for side, res, label in (("source", env.source, _("source")), ("destination", env.destination, _("destination"))):
        ep = getattr(job, side)
        name = ep.volume_label or _("the drive")
        if res.state is EndpointState.MISSING:
            level = WARNING if job.drive.wait_for_drive else ERROR
            issues.append(Issue(level, f"{side}.path",
                                _("Connect {drive} to use the {side} folder.").format(drive=name, side=label),
                                _("The job waits up to {n} minutes for it.").format(n=job.drive.wait_minutes)
                                if job.drive.wait_for_drive else _("Plug in the drive, or turn on \"Wait for the drive\".")))
        elif res.state is EndpointState.LOCKED and not job.drive.unlock_encrypted:
            issues.append(Issue(ERROR, f"{side}.path", _("{drive} is locked.").format(drive=name),
                                _("Unlock it from the sidebar, or turn on \"Unlock the encrypted drive before running\".")))
        elif res.state is EndpointState.NOT_MOUNTED and not env.udisks:
            issues.append(Issue(ERROR, f"{side}.path", _("{drive} is not mounted.").format(drive=name),
                                _("Mount it in your file manager first.")))
    if env.source.state is EndpointState.READY and not env.source_exists:
        issues.append(Issue(ERROR, "source.path", _("The source folder does not exist: {path}").format(path=env.source.path),
                            _("Check the path or pick the folder again.")))
    if not env.rsync_path or env.rsync_version is None:
        issues.append(Issue(ERROR, "engine", _("rsync is not installed, so jobs cannot run."),
                            _("Install it, for example: sudo apt install rsync")))


def _drive_steps(job: SyncJob, env: PlanEnv) -> tuple[list[Step], list[Step]]:
    before: list[Step] = []
    after: list[Step] = []
    seen: set[str] = set()
    for res in (env.source, env.destination):
        if res.state is EndpointState.LOCKED and res.container is not None and res.container.uuid not in seen:
            seen.add(res.container.uuid)
            before.append(Step(StepKind.UNLOCK, _("unlock and mount {drive} (UDisks2)").format(drive=res.container.label),
                               params={"container_uuid": res.container.uuid}))
        elif res.state is EndpointState.NOT_MOUNTED and res.drive is not None and res.drive.uuid not in seen:
            seen.add(res.drive.uuid)
            before.append(Step(StepKind.MOUNT, _("mount {drive} (UDisks2)").format(drive=res.drive.label),
                               params={"uuid": res.drive.uuid}))
    dest_ep = job.destination
    dest_drive: DriveInfo | None = env.destination.drive
    label = dest_ep.volume_label or (dest_drive.label if dest_drive else _("the drive"))
    if job.drive.lock_after and (dest_ep.container_uuid or (dest_drive and dest_drive.container_uuid)):
        container = dest_ep.container_uuid or (dest_drive.container_uuid if dest_drive else None)
        after.append(Step(StepKind.UNMOUNT, _("unmount {drive}").format(drive=label), params={"uuid": dest_ep.volume_uuid}))
        after.append(Step(StepKind.LOCK, _("lock {drive}").format(drive=label), params={"container_uuid": container}))
    if job.drive.eject_after:
        for side in ("destination", "source"):
            ep = getattr(job, side)
            if ep.kind is DriveKind.REMOVABLE and ep.volume_uuid:
                name = ep.volume_label or _("the drive")
                if not any(s.kind is StepKind.UNMOUNT and s.params.get("uuid") == ep.volume_uuid for s in after):
                    after.append(Step(StepKind.UNMOUNT, _("unmount {drive}").format(drive=name), params={"uuid": ep.volume_uuid}))
                after.append(Step(StepKind.POWER_OFF, _("eject {drive}").format(drive=name), params={"uuid": ep.volume_uuid}))
                break
    return before, after


def plan_job(job: SyncJob, env: PlanEnv, preview: bool = False, dry_run: bool = False) -> Plan:
    """Build the plan. ``preview`` = itemised dry run for the Preview dialog."""
    issues = validate_job(job)
    _endpoint_issues(job, env, issues)
    eff, notes = _adjust_for_environment(job, env, issues)
    src, dst = env.source.path, env.destination.path
    opts = rb.BuildOptions(
        dry_run=dry_run, preview=preview, priority_wrapper=() if preview else _priority(eff, env),
        rsync_path=env.rsync_path or "rsync", rsync_version=env.rsync_version or (0, 0, 0),
    )
    fs = env.dest_fs
    before, after = _drive_steps(eff, env) if not (preview or dry_run) else ([], [])
    steps: list[Step] = list(before)

    if eff.mode is Mode.TWO_WAY:
        steps.append(Step(StepKind.TWOWAY, _("two-way sync: compare both sides, then copy each way"),
                          params={"source": src, "destination": dst, "preview": preview or dry_run}))
    elif eff.safety.snapshots:
        link_dest = eff.safety.link_dest or (os.path.join(dst, LATEST) if env.latest_snapshot_exists else None)
        if preview or dry_run:
            # Show what changed since the latest snapshot.
            target = os.path.join(dst, LATEST) if env.latest_snapshot_exists else os.path.join(dst, "new-snapshot")
            argv = rb.build_rsync_argv(eff, src, target, fs, opts)
            steps.append(Step(StepKind.RSYNC, _("compare with the latest snapshot"), argv))
        else:
            name = env.now.strftime(SNAPSHOT_FORMAT)
            target = os.path.join(dst, name)
            argv = rb.build_rsync_argv(eff, src, target, fs, replace(opts, link_dest=link_dest))
            steps.append(Step(StepKind.RSYNC, _("copy into a new snapshot"), argv, {"snapshot": name, "target": target}))
            steps.append(Step(StepKind.UPDATE_LATEST, _("point \"latest\" at the new snapshot"),
                              ["ln", "-sfn", name, os.path.join(dst, LATEST)], {"root": dst, "name": name}))
            steps.append(Step(StepKind.ROTATE,
                              _("rotate: keep {d} daily, {w} weekly").format(d=eff.safety.keep_daily, w=eff.safety.keep_weekly),
                              params={"root": dst, "keep_daily": eff.safety.keep_daily, "keep_weekly": eff.safety.keep_weekly}))
    elif eff.safety.atomic and not (preview or dry_run):
        parent, base = os.path.split(dst.rstrip("/"))
        stage = os.path.join(parent, f".{base}.lfc-stage")
        if env.dest_exists:
            steps.append(Step(StepKind.HARDLINK_CLONE, _("prepare a staging copy (hard links, no extra space)"),
                              params={"source": dst, "target": stage}))
        argv = rb.build_rsync_argv(eff, src, stage, fs, opts)
        steps.append(Step(StepKind.RSYNC, _("copy changes into the staging copy"), argv, {"target": stage}))
        steps.append(Step(StepKind.SWAP, _("swap the staging copy into place in one step"),
                          params={"stage": stage, "target": dst, "exists": env.dest_exists}))
        if env.dest_exists:
            steps.append(Step(StepKind.REMOVE_TREE, _("remove the previous version"), params={"path": stage}))
    elif eff.performance.parallel_streams > 1 and not (preview or dry_run):
        argv = rb.build_rsync_argv(eff, src, dst, fs, replace(opts, files_from="<bucket>"))
        steps.append(Step(StepKind.PARALLEL_RSYNC,
                          _("copy with {n} parallel rsync streams (split by top-level folder)").format(n=eff.performance.parallel_streams),
                          argv, {"streams": eff.performance.parallel_streams, "source": src, "destination": dst}))
    else:
        argv = rb.build_rsync_argv(eff, src, dst, fs, opts)
        steps.append(Step(StepKind.RSYNC, _("copy"), argv))
    steps += after
    return Plan(eff, steps, issues, src, dst, notes)


def gather_env(
    job: SyncJob,
    drives: list[DriveInfo],
    rsync_path: str | None,
    rsync_version: tuple[int, int, int] | None,
    has_ionice: bool,
    has_nice: bool,
    udisks: bool,
) -> PlanEnv:
    """Collect filesystem facts for :func:`plan_job`. Touches the disk: call off the main thread."""
    src = resolve_endpoint(job.source, drives)
    dst = resolve_endpoint(job.destination, drives)
    fs_type = None
    if dst.drive is not None:
        fs_type = dst.drive.fs_type
    elif dst.state is EndpointState.READY and dst.path:
        fs_type = fs_type_for_path(dst.path)
    fs_type = fs_type or job.destination.fs_type
    return PlanEnv(
        source=src, destination=dst, dest_fs=capabilities_for(fs_type),
        source_exists=bool(src.path) and os.path.isdir(src.path) if src.state is EndpointState.READY else True,
        dest_exists=bool(dst.path) and os.path.isdir(dst.path),
        latest_snapshot_exists=bool(dst.path) and os.path.isdir(os.path.join(dst.path, LATEST)),
        rsync_path=rsync_path, rsync_version=rsync_version, has_ionice=has_ionice, has_nice=has_nice,
        udisks=udisks,
    )
