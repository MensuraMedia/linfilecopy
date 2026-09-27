"""Enumerations used by the job model. Values are stable strings stored in JSON."""
from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """``str`` enum whose value is what gets serialised."""

    def __str__(self) -> str:
        return self.value


class Mode(StrEnum):
    COPY = "copy"          # B2: add and update, never delete
    MIRROR = "mirror"      # B2: make destination identical (deletes extras)
    TWO_WAY = "two_way"    # #13: propagate changes both ways


class OverwritePolicy(StrEnum):
    ALWAYS = "overwrite"   # B9: replace changed files
    SKIP = "skip"          # --ignore-existing
    NEWER = "newer"        # --update


class CompareMethod(StrEnum):
    SIZE_TIME = "size_time"  # rsync default quick check
    SIZE_ONLY = "size_only"  # --size-only


class ConflictPolicy(StrEnum):
    NEWER = "newer"          # most recently modified wins
    LARGER = "larger"        # larger file wins
    KEEP_BOTH = "keep_both"  # rename the loser, keep both
    SOURCE = "source"        # source side always wins
    ASK = "ask"              # stop and list conflicts


class DriveKind(StrEnum):
    INTERNAL = "internal"
    REMOVABLE = "removable"
    ARRAY = "array"
    UNKNOWN = "unknown"


class SymlinkPolicy(StrEnum):
    KEEP = "keep"      # -l copy links as links
    FOLLOW = "follow"  # -L copy what they point to
    SKIP = "skip"      # leave them out


class FilterAction(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"


class ExcludePreset(StrEnum):
    HIDDEN = "hidden"
    CACHE = "cache"
    TEMP = "temp"
    SYSTEM = "system"


class SpeedUnit(StrEnum):
    KB = "KB"
    MB = "MB"


class LogLevel(StrEnum):
    QUIET = "quiet"
    NORMAL = "normal"
    VERBOSE = "verbose"
    DEBUG = "debug"


class ScheduleKind(StrEnum):
    NONE = "none"
    ONCE = "once"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    CUSTOM = "custom"      # cron expression


class ScheduleBackend(StrEnum):
    AUTO = "auto"          # systemd user timer if available, else cron
    SYSTEMD = "systemd"
    CRON = "cron"


class RunStatus(StrEnum):
    QUEUED = "queued"
    WAITING = "waiting"    # e.g. drive locked or not connected
    RUNNING = "running"
    PAUSED = "paused"
    SUCCESS = "success"
    WARNING = "warning"    # finished with non-fatal problems (rsync 24)
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def finished(self) -> bool:
        return self in (RunStatus.SUCCESS, RunStatus.WARNING, RunStatus.FAILED, RunStatus.CANCELLED)


class Trigger(StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    FILE_CHANGE = "file_change"
    DRIVE_CONNECTED = "drive_connected"
    RETRY = "retry"
