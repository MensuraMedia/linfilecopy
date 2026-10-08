"""The SyncJob model: one object holds the complete configuration of a job.

Groups are nested dataclasses so each maps to one designer section and one
builder function. Serialisation is tolerant in both directions: unknown keys
are ignored and missing keys take defaults, so older and newer job files load.

Feature references (B = basic, # = top-20) follow docs/CONCEPT.md §6.
"""
from __future__ import annotations

import copy
import dataclasses
import re
import secrets
import time
import types
import typing
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from linfilecopy.model.enums import (
    CompareMethod,
    ConflictPolicy,
    DriveKind,
    ExcludePreset,
    FilterAction,
    LogLevel,
    Mode,
    OverwritePolicy,
    ScheduleBackend,
    ScheduleKind,
    SpeedUnit,
    SymlinkPolicy,
)

SCHEMA_VERSION = 2
JOB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass
class Endpoint:
    """A source or destination folder on a local or attached drive (B1, #20)."""

    path: str = ""
    volume_uuid: str | None = None     # filesystem UUID, resolves a moved mount point
    volume_label: str | None = None    # display name, e.g. "62 GB Volume"
    relative_path: str | None = None   # path inside the volume
    kind: DriveKind = DriveKind.UNKNOWN
    fs_type: str | None = None         # last seen filesystem type (informational)
    container_uuid: str | None = None  # LUKS container holding the volume (#10)


@dataclass
class FilterRule:
    """One ordered include/exclude rule (#5). Patterns use rsync syntax."""

    action: FilterAction = FilterAction.EXCLUDE
    pattern: str = ""


@dataclass
class TransferOptions:
    copy_contents: bool = True           # B1: copy what is inside the folder (trailing /)
    delta: bool = False                  # #1: --no-whole-file (local rsync defaults to whole files)
    inplace: bool = False                # #1: --inplace
    compare: CompareMethod = CompareMethod.SIZE_TIME  # #2
    checksum: bool = False               # #8: -c
    resume: bool = True                  # #7: --partial --partial-dir
    sparse: bool = False                 # #15: -S


@dataclass
class PerformanceOptions:
    limit_speed: bool = False            # #6
    speed_limit: float = 50.0
    speed_unit: SpeedUnit = SpeedUnit.MB
    low_priority: bool = False           # #6: ionice -c3 nice -n19
    parallel_streams: int = 1            # #12


@dataclass
class MetadataOptions:
    """#3 / B5. In the Simple view one switch controls permissions + times."""

    permissions: bool = True
    times: bool = True
    owner: bool = False
    group: bool = False
    acls: bool = False
    xattrs: bool = False
    hardlinks: bool = False
    devices: bool = False
    symlinks: SymlinkPolicy = SymlinkPolicy.KEEP

    @property
    def basic(self) -> bool:
        """State of the Simple view's "Keep dates and permissions" switch."""
        return self.permissions and self.times

    def set_basic(self, on: bool) -> None:
        self.permissions = on
        self.times = on


@dataclass
class FilterOptions:
    presets: list[ExcludePreset] = field(default_factory=lambda: [ExcludePreset.CACHE, ExcludePreset.TEMP])
    rules: list[FilterRule] = field(default_factory=list)
    exclude_from: str | None = None      # --exclude-from
    files_from: str | None = None        # --files-from


@dataclass
class SafetyOptions:
    atomic: bool = False                 # #16
    snapshots: bool = False              # #17
    link_dest: str | None = None         # None = latest snapshot (automatic)
    keep_daily: int = 14
    keep_weekly: int = 8


@dataclass
class TwoWayOptions:
    conflict: ConflictPolicy = ConflictPolicy.NEWER   # #13
    use_trash: bool = True
    delete_guard_percent: int = 50


@dataclass
class DriveOptions:
    unlock_encrypted: bool = False       # #10
    remember_passphrase: bool = False
    lock_after: bool = False
    eject_after: bool = False            # #20 / B10
    wait_for_drive: bool = False
    wait_minutes: int = 10


@dataclass
class TriggerOptions:
    on_change: bool = False              # #14
    watch_paths: list[str] = field(default_factory=list)   # empty = the source folder
    debounce_seconds: float = 2.0
    on_drive_connected: bool = False     # #19/#20: run when the job's removable drive appears


@dataclass
class LoggingOptions:
    level: LogLevel = LogLevel.NORMAL    # #18
    notify_success: bool = True          # B10
    notify_failure: bool = True
    retries: int = 0
    retry_delay_seconds: int = 30


@dataclass
class ScheduleOptions:
    kind: ScheduleKind = ScheduleKind.NONE   # #19
    time: str = "03:00"                      # HH:MM for daily/weekly/once
    weekdays: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])  # 0 = Monday
    once_date: str = ""                      # YYYY-MM-DD
    minute: int = 0                          # hourly: minute past the hour
    cron: str = ""                           # custom: 5-field cron expression
    backend: ScheduleBackend = ScheduleBackend.AUTO
    enabled: bool = False
    persistent: bool = True                  # catch up missed runs
    ac_power_only: bool = False


@dataclass
class SyncJob:
    """A complete copy/sync job. Everything the engine needs lives here."""

    id: str = ""
    name: str = ""
    description: str = ""
    source: Endpoint = field(default_factory=Endpoint)
    extra_sources: list[Endpoint] = field(default_factory=list)   # additional source folders/drives (Copy only)
    destination: Endpoint = field(default_factory=Endpoint)
    mode: Mode = Mode.COPY
    overwrite: OverwritePolicy = OverwritePolicy.ALWAYS
    preview_first: bool = True
    transfer: TransferOptions = field(default_factory=TransferOptions)
    performance: PerformanceOptions = field(default_factory=PerformanceOptions)
    metadata: MetadataOptions = field(default_factory=MetadataOptions)
    filters: FilterOptions = field(default_factory=FilterOptions)
    safety: SafetyOptions = field(default_factory=SafetyOptions)
    twoway: TwoWayOptions = field(default_factory=TwoWayOptions)
    drive: DriveOptions = field(default_factory=DriveOptions)
    triggers: TriggerOptions = field(default_factory=TriggerOptions)
    logging: LoggingOptions = field(default_factory=LoggingOptions)
    schedule: ScheduleOptions = field(default_factory=ScheduleOptions)
    template: str | None = None
    created: float = 0.0
    modified: float = 0.0
    schema_version: int = SCHEMA_VERSION

    # ----- sources -------------------------------------------------------
    @property
    def source_endpoints(self) -> list[Endpoint]:
        """The primary source plus any extra sources that have a path (B1, multi-source)."""
        return [ep for ep in (self.source, *self.extra_sources) if (ep.path or "").strip()]

    @property
    def multi_source(self) -> bool:
        """True when more than one source folder/drive is chosen."""
        return len(self.source_endpoints) > 1

    # ----- identity ------------------------------------------------------
    @staticmethod
    def make_id(name: str) -> str:
        """A filesystem- and unit-name-safe id: slug of the name + random suffix."""
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "job"
        return f"{slug}-{secrets.token_hex(2)}"

    def ensure_identity(self) -> "SyncJob":
        now = time.time()
        if not self.id or not JOB_ID_RE.match(self.id):
            self.id = self.make_id(self.name)
        if not self.created:
            self.created = now
        return self

    def clone(self, new_name: str | None = None) -> "SyncJob":
        """Deep copy with a fresh id (Duplicate job)."""
        job = copy.deepcopy(self)
        job.name = new_name or self.name
        job.id = self.make_id(job.name)
        job.created = job.modified = 0.0
        job.schedule.enabled = False
        return job.ensure_identity()

    # ----- serialisation -------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return _to_plain(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SyncJob":
        data = migrate(dict(data))
        return _from_plain(cls, data)


# ---------------------------------------------------------------------------
# generic (de)serialisation for the nested dataclasses above

def _to_plain(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return {f.name: _to_plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, list):
        return [_to_plain(v) for v in obj]
    return obj


def _convert(tp: Any, value: Any, default: Any) -> Any:
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Union or origin is types.UnionType:
        if value is None:
            return None
        non_none = [a for a in args if a is not type(None)]
        return _convert(non_none[0], value, default) if non_none else value
    if origin is list:
        if not isinstance(value, list):
            return default
        inner = args[0] if args else Any
        out = []
        for v in value:
            converted = _convert(inner, v, None)
            if converted is not None:
                out.append(converted)
        return out
    if isinstance(tp, type) and dataclasses.is_dataclass(tp):
        return _from_plain(tp, value) if isinstance(value, dict) else default
    if isinstance(tp, type) and issubclass(tp, Enum):
        try:
            return tp(value)
        except ValueError:
            return default
    if tp is bool:
        return value if isinstance(value, bool) else default
    if tp is int:
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default
    if tp is float:
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default
    if tp is str:
        return value if isinstance(value, str) else default
    return value


def _from_plain(cls: type, data: dict[str, Any]) -> Any:
    hints = typing.get_type_hints(cls)
    instance = cls()
    for f in dataclasses.fields(cls):
        if f.name in data:
            setattr(instance, f.name, _convert(hints[f.name], data[f.name], getattr(instance, f.name)))
    return instance


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade older job files in place. v1 (concept 0.1) had network/compression fields."""
    version = int(data.get("schema_version", 1) or 1)
    if version < 2:
        transfer = data.get("transfer", {}) or {}
        transfer.pop("compress", None)
        transfer.pop("compress_level", None)
        data["transfer"] = transfer
        for side in ("source", "destination"):
            ep = data.get(side) or {}
            ep.pop("host", None)
            ep.pop("user", None)
            ep.pop("port", None)
            ep.pop("key_file", None)
            ep.pop("remote_name", None)
            data[side] = ep
    data["schema_version"] = SCHEMA_VERSION
    return data
