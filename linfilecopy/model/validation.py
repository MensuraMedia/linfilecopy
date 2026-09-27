"""Structural validation of a SyncJob.

These checks need no knowledge of the running system. Environment checks
(filesystem capabilities, free space, rsync version, tool availability) are
added by the engine planner. Every issue carries a suggested fix.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from linfilecopy.i18n import _
from linfilecopy.model import cron
from linfilecopy.model.enums import CompareMethod, DriveKind, Mode, ScheduleKind
from linfilecopy.model.job import SyncJob

ERROR = "error"
WARNING = "warning"
INFO = "info"

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Folders that must never be the target of a job that deletes files.
PROTECTED = {"/", "/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/lib64", "/media", "/mnt",
             "/opt", "/proc", "/root", "/run", "/sbin", "/srv", "/sys", "/tmp", "/usr", "/var"}


@dataclass(frozen=True)
class Issue:
    level: str       # "error" | "warning" | "info"
    field: str       # dotted job field, e.g. "safety.atomic"
    message: str
    fix: str = ""

    @property
    def blocking(self) -> bool:
        return self.level == ERROR


def _norm(path: str) -> str:
    return os.path.normpath(path) if path else ""


def _inside(child: str, parent: str) -> bool:
    child, parent = _norm(child), _norm(parent)
    return child != parent and (child + os.sep).startswith(parent.rstrip(os.sep) + os.sep)


def protected_paths() -> set[str]:
    return PROTECTED | {_norm(os.path.expanduser("~"))}


def _real(path: str) -> str:
    """Normalised path with symlinks resolved (so two spellings of one folder compare equal)."""
    return os.path.realpath(path) if path else ""


def is_protected(path: str) -> bool:
    """System/home folders, and folders that hold other drives' mount points
    (/media/<user>, /run/media/<user>): deleting inside them would reach every mounted drive."""
    for p in {_norm(path), _real(path)}:
        if p in protected_paths():
            return True
        parts = p.strip("/").split("/")
        if (parts[:1] == ["media"] and len(parts) == 2) or (parts[:2] == ["run", "media"] and len(parts) == 3):
            return True
    return False


def validate_job(job: SyncJob) -> list[Issue]:
    """Return every structural problem with ``job`` (empty list = valid)."""
    issues: list[Issue] = []
    add = issues.append
    src, dst = job.source.path.strip(), job.destination.path.strip()

    # ----- identity and paths (B1) -------------------------------------------
    if not job.name.strip():
        add(Issue(ERROR, "name", _("The job has no name."), _("Type a name at the top of the designer.")))
    if not src:
        add(Issue(ERROR, "source.path", _("Choose a source folder."), _("Drop a folder on the source field or press Browse.")))
    elif not os.path.isabs(src):
        add(Issue(ERROR, "source.path", _("The source must be a full path starting with /."), _("Use Browse to pick the folder.")))
    if not dst:
        add(Issue(ERROR, "destination.path", _("Choose a destination folder."), _("Drop a folder on the destination field or press Browse.")))
    elif not os.path.isabs(dst):
        add(Issue(ERROR, "destination.path", _("The destination must be a full path starting with /."), _("Use Browse to pick the folder.")))

    if src and dst and os.path.isabs(src) and os.path.isabs(dst):
        src_inside_dst = _inside(src, dst) or _inside(_real(src), _real(dst))
        if _norm(src) == _norm(dst) or _real(src) == _real(dst):
            add(Issue(ERROR, "destination.path", _("Source and destination are the same folder."), _("Pick a different destination.")))
        elif _inside(dst, src) and not job.safety.snapshots:
            add(Issue(ERROR, "destination.path",
                      _("The destination is inside the source, so the copy would include itself."),
                      _("Choose a destination outside the source folder.")))
        elif _inside(dst, src):
            add(Issue(ERROR, "destination.path",
                      _("The snapshot folder is inside the source, so each snapshot would copy the previous ones."),
                      _("Choose a destination outside the source folder.")))
        elif src_inside_dst and job.mode in (Mode.MIRROR, Mode.TWO_WAY):
            add(Issue(ERROR, "destination.path",
                      _("The source is inside the destination. Mirror and two-way would delete the source itself."),
                      _("Choose a destination that does not contain the source folder.")))
        elif src_inside_dst:
            add(Issue(WARNING, "destination.path",
                      _("The source is inside the destination, so its files are copied next to it."),
                      _("Usually a mistake: choose a destination that does not contain the source folder.")))
        if job.mode in (Mode.MIRROR, Mode.TWO_WAY) and is_protected(dst):
            add(Issue(ERROR, "destination.path",
                      _("{path} is a system or home folder. Mirror and two-way jobs could delete files there.").format(path=dst),
                      _("Choose a dedicated folder, for example a folder on a backup drive.")))
        if job.mode is Mode.TWO_WAY and is_protected(src):
            add(Issue(ERROR, "source.path",
                      _("{path} is a system or home folder. Two-way jobs can delete files on both sides.").format(path=src),
                      _("Choose a specific folder such as ~/Notes.")))

    # ----- mode combinations (B2, #13, #16, #17, #12) ---------------------------
    if job.mode is Mode.MIRROR:
        add(Issue(INFO, "mode", _("Mirror deletes files at the destination that are not in the source."),
                  _("You will be asked to confirm before anything is deleted.")))
    if job.mode is Mode.TWO_WAY:
        if job.safety.snapshots or job.safety.atomic:
            add(Issue(ERROR, "mode", _("Two-way sync cannot be combined with snapshots or atomic replace."),
                      _("Turn off snapshots and atomic replace, or use Copy or Mirror.")))
        if job.performance.parallel_streams > 1:
            add(Issue(ERROR, "performance.parallel_streams", _("Parallel streams are not available for two-way sync."),
                      _("Set parallel streams to 1.")))
        if job.filters.files_from:
            add(Issue(ERROR, "filters.files_from", _("Two-way sync cannot use a list of files."),
                      _("Clear \"Only files listed in\" or use Copy.")))
    if job.safety.atomic and job.safety.snapshots:
        add(Issue(ERROR, "safety.atomic", _("Atomic replace is not needed with snapshots: each snapshot is written to a new folder."),
                  _("Turn off atomic replace.")))
    if job.performance.parallel_streams > 1 and job.filters.files_from:
        add(Issue(ERROR, "performance.parallel_streams",
                  _("Parallel streams cannot be combined with \"Copy only files listed in\"."),
                  _("Set parallel streams to 1, or clear the file list.")))
    if job.performance.parallel_streams > 1 and (job.safety.atomic or job.safety.snapshots):
        add(Issue(ERROR, "performance.parallel_streams",
                  _("Parallel streams are not available with snapshots or atomic replace yet."),
                  _("Set parallel streams to 1, or turn off snapshots and atomic replace.")))
    if not 1 <= job.performance.parallel_streams <= 16:
        add(Issue(ERROR, "performance.parallel_streams", _("Parallel streams must be between 1 and 16."), ""))
    if job.transfer.inplace and (job.safety.atomic or job.safety.snapshots):
        add(Issue(ERROR, "transfer.inplace",
                  _("Updating files in place would change files shared with older snapshots or the live copy."),
                  _("Turn off \"Update files in place\".")))
    if job.transfer.inplace and job.transfer.resume:
        add(Issue(INFO, "transfer.inplace", _("With in-place updates, interrupted files are resumed in place."), ""))

    # ----- comparison, metadata (#2, #3, #8) ----------------------------------
    if job.transfer.checksum and job.transfer.compare is CompareMethod.SIZE_ONLY:
        add(Issue(WARNING, "transfer.compare", _("Checksums replace the size-only comparison."),
                  _("Set \"Decide what changed by\" to size and time, or turn off checksums.")))
    if job.metadata.owner or job.metadata.group:
        add(Issue(WARNING, "metadata.owner",
                  _("Keeping owner and group only works when the job runs as root. Otherwise files are owned by you."),
                  _("Turn off Owner and Group unless you run LinFileCopy as root.")))

    # ----- filters (#5) ----------------------------------------------------------
    for i, rule in enumerate(job.filters.rules):
        if not rule.pattern.strip():
            add(Issue(ERROR, f"filters.rules.{i}", _("Filter rule {n} is empty.").format(n=i + 1), _("Type a pattern or remove the rule.")))
    for fld, value in (("filters.exclude_from", job.filters.exclude_from), ("filters.files_from", job.filters.files_from)):
        if value and not os.path.isabs(value):
            add(Issue(ERROR, fld, _("List files must be full paths."), _("Use the file picker.")))

    # ----- speed (#6) ------------------------------------------------------------
    if job.performance.limit_speed and job.performance.speed_limit <= 0:
        add(Issue(ERROR, "performance.speed_limit", _("The speed limit must be more than 0."), _("Enter a speed, or turn the limit off.")))

    # ----- drives (#10, #20) -----------------------------------------------------
    uuids = [e.volume_uuid for e in (job.source, job.destination) if e.volume_uuid]
    if job.drive.unlock_encrypted and not uuids:
        add(Issue(ERROR, "drive.unlock_encrypted", _("Unlocking needs a drive picked from the drive list."),
                  _("Choose the encrypted drive with the drive button, or turn this off.")))
    if job.triggers.on_drive_connected and not uuids:
        add(Issue(ERROR, "triggers.on_drive_connected", _("\"When drive connected\" needs a drive picked from the drive list."),
                  _("Choose the drive with the drive button.")))
    removable = any(e.kind is DriveKind.REMOVABLE for e in (job.source, job.destination))
    if job.drive.eject_after and not removable:
        add(Issue(WARNING, "drive.eject_after", _("Neither folder is on a removable drive, so there is nothing to eject."),
                  _("Turn off \"Eject when finished\".")))

    # ----- logging (#18) -----------------------------------------------------------
    if not 0 <= job.logging.retries <= 10:
        add(Issue(ERROR, "logging.retries", _("Retries must be between 0 and 10."), ""))
    if not 1 <= job.twoway.delete_guard_percent <= 100:
        add(Issue(ERROR, "twoway.delete_guard_percent", _("The delete guard must be between 1 and 100 %."), ""))

    # ----- schedule (#19) ----------------------------------------------------------
    sch = job.schedule
    if sch.kind in (ScheduleKind.ONCE, ScheduleKind.DAILY, ScheduleKind.WEEKLY) and not TIME_RE.match(sch.time):
        add(Issue(ERROR, "schedule.time", _("Enter the time as HH:MM, for example 03:00."), ""))
    if sch.kind is ScheduleKind.WEEKLY and not sch.weekdays:
        add(Issue(ERROR, "schedule.weekdays", _("Pick at least one day of the week."), ""))
    if sch.kind is ScheduleKind.ONCE and not DATE_RE.match(sch.once_date):
        add(Issue(ERROR, "schedule.once_date", _("Pick the date for the one-time run."), ""))
    if sch.kind is ScheduleKind.HOURLY and not 0 <= sch.minute <= 59:
        add(Issue(ERROR, "schedule.minute", _("The minute must be between 0 and 59."), ""))
    if sch.kind is ScheduleKind.CUSTOM:
        try:
            cron.parse(sch.cron)
        except cron.CronError as exc:
            add(Issue(ERROR, "schedule.cron", str(exc), _("Example: 30 2 * * 1-5 runs at 02:30 on weekdays.")))
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(i.blocking for i in issues)
