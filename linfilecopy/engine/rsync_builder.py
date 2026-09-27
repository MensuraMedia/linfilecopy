"""SyncJob -> rsync argv. Pure functions: no I/O, fully golden-tested.

Every rsync flag the app can produce is decided here (project rule 6). The
destination filesystem's capabilities are applied by dropping options it
cannot store; the planner reports those adjustments to the user.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from linfilecopy.engine.filesystems import FsCapabilities, capabilities_for
from linfilecopy.model.enums import (
    CompareMethod,
    ExcludePreset,
    FilterAction,
    LogLevel,
    Mode,
    OverwritePolicy,
    SpeedUnit,
    SymlinkPolicy,
)
from linfilecopy.model.job import SyncJob

PARTIAL_DIR = ".lfc-partial"
TRASH_DIR = ".lfc-trash"
PROGRESS_INFO = "--info=progress2,name1,stats2"
PREVIEW_FORMAT = "%i %l %n%L"

# B6 quick presets. Patterns use rsync syntax; a trailing / matches directories only.
PRESET_PATTERNS: dict[ExcludePreset, list[str]] = {
    ExcludePreset.HIDDEN: [".*"],
    ExcludePreset.CACHE: [".cache/", "__pycache__/", "node_modules/", ".thumbnails/", "*.pyc"],
    ExcludePreset.TEMP: ["*.tmp", "*.temp", "*~", ".~lock*", "*.swp", "*.part", "*.crdownload"],
    ExcludePreset.SYSTEM: ["lost+found/", ".Trash-*/", "System Volume Information/", "$RECYCLE.BIN/",
                           ".Spotlight-V100/", ".fseventsd/", ".DS_Store", "Thumbs.db", "desktop.ini"],
}
# Our own working folders are never copied.
INTERNAL_EXCLUDES = [f"{TRASH_DIR}/", ".lfc-stage/"]


@dataclass(frozen=True)
class BuildOptions:
    """Per-invocation knobs that are not part of the saved job."""

    dry_run: bool = False
    preview: bool = False                 # itemised change list instead of progress
    link_dest: str | None = None          # absolute path for --link-dest
    files_from: str | None = None         # overrides job.filters.files_from (parallel buckets)
    delete: bool | None = None            # override Mirror deletion (atomic stage uses it)
    priority_wrapper: tuple[str, ...] = field(default_factory=tuple)   # e.g. ("ionice","-c3","nice","-n19")
    rsync_path: str = "rsync"
    rsync_version: tuple[int, int, int] = (3, 2, 7)


def with_trailing_slash(path: str) -> str:
    return path if path.endswith("/") else path + "/"


def without_trailing_slash(path: str) -> str:
    return path.rstrip("/") or "/"


def short_flags(job: SyncJob, fs: FsCapabilities) -> str:
    """The combined short-option cluster, e.g. ``-rlptgoAXHS``."""
    md = job.metadata
    flags = "r"
    symlinks = effective_symlinks(job, fs)
    if symlinks is SymlinkPolicy.KEEP:
        flags += "l"
    elif symlinks is SymlinkPolicy.FOLLOW:
        flags += "L"
    if md.permissions and fs.permissions:
        flags += "p"
    if md.times:
        flags += "t"
    if md.group and fs.owner:
        flags += "g"
    if md.owner and fs.owner:
        flags += "o"
    if md.devices and fs.permissions:
        flags += "D"
    if md.acls and fs.acl_xattr:
        flags += "A"
    if md.xattrs and fs.acl_xattr:
        flags += "X"
    if md.hardlinks and fs.hardlinks:
        flags += "H"
    if job.transfer.sparse:
        flags += "S"
    if job.transfer.checksum:
        flags += "c"
    return "-" + flags


def effective_symlinks(job: SyncJob, fs: FsCapabilities) -> SymlinkPolicy:
    """Links cannot be stored on FAT/exFAT: "keep" becomes "skip" there."""
    policy = job.metadata.symlinks
    if policy is SymlinkPolicy.KEEP and not fs.symlinks:
        return SymlinkPolicy.SKIP
    return policy


def speed_limit_kib(job: SyncJob) -> int | None:
    """--bwlimit value in KiB/s (rsync's unit), or None when unlimited."""
    perf = job.performance
    if not perf.limit_speed or perf.speed_limit <= 0:
        return None
    factor = 1024 if perf.speed_unit is SpeedUnit.MB else 1
    return max(1, int(round(perf.speed_limit * factor)))


def filter_args(job: SyncJob, include_internal: bool = True) -> list[str]:
    """Ordered include/exclude options: user rules first so they override presets."""
    args: list[str] = []
    for rule in job.filters.rules:
        pattern = rule.pattern.strip()
        if pattern:
            opt = "--include" if rule.action is FilterAction.INCLUDE else "--exclude"
            args.append(f"{opt}={pattern}")
    for preset in job.filters.presets:
        args += [f"--exclude={p}" for p in PRESET_PATTERNS[preset]]
    if include_internal:
        args += [f"--exclude={p}" for p in INTERNAL_EXCLUDES]
    if job.filters.exclude_from:
        args.append(f"--exclude-from={job.filters.exclude_from}")
    return args


def build_rsync_argv(
    job: SyncJob,
    source: str,
    destination: str,
    fs: FsCapabilities | None = None,
    opts: BuildOptions | None = None,
) -> list[str]:
    """Build the full argv (including any priority wrapper) for one rsync run."""
    opts = opts or BuildOptions()
    fs = fs or capabilities_for(job.destination.fs_type)
    t = job.transfer
    argv: list[str] = [*opts.priority_wrapper, opts.rsync_path, short_flags(job, fs)]

    if fs.coarse_times:
        argv.append("--modify-window=1")                        # FAT/exFAT time precision
    if t.compare is CompareMethod.SIZE_ONLY and not t.checksum:
        argv.append("--size-only")                              # #2
    if job.overwrite is OverwritePolicy.SKIP:
        argv.append("--ignore-existing")                        # B9
    elif job.overwrite is OverwritePolicy.NEWER:
        argv.append("--update")
    if t.delta:
        argv.append("--no-whole-file")                          # #1 (local default is whole-file)
    if t.inplace:
        argv.append("--inplace")
    if t.resume:                                                # #7
        argv.append("--partial")
        if not t.inplace:
            argv.append(f"--partial-dir={PARTIAL_DIR}")
    delete = (job.mode is Mode.MIRROR) if opts.delete is None else opts.delete
    if delete:
        argv.append("--delete-delay")                           # B2 mirror
    bw = speed_limit_kib(job)
    if bw:
        argv.append(f"--bwlimit={bw}")                          # #6
    if opts.link_dest:
        argv.append(f"--link-dest={opts.link_dest}")            # #16/#17

    if opts.preview:
        argv += ["--dry-run", "--itemize-changes", f"--out-format={PREVIEW_FORMAT}", "--info=stats2"]
    else:
        if opts.dry_run:
            argv.append("--dry-run")
        argv += [PROGRESS_INFO, "--no-inc-recursive", "--outbuf=L"]   # B3/#11
    if job.logging.level is LogLevel.VERBOSE:
        argv.append("-v")
    elif job.logging.level is LogLevel.DEBUG:
        argv.append("-vv")

    argv += filter_args(job)                                    # B6/#5
    files_from = opts.files_from or job.filters.files_from
    if files_from:
        argv.append(f"--files-from={files_from}")

    src = with_trailing_slash(source) if t.copy_contents else without_trailing_slash(source)
    argv += [src, with_trailing_slash(destination)]
    return argv


def display_command(argv: list[str]) -> str:
    """Shell-quoted command for the preview pane and clipboard (never executed)."""
    return shlex.join(argv)


def wrapped_display(argv: list[str], width: int = 60) -> str:
    """Multi-line display: one logical group per line, continuation backslashes."""
    lines: list[str] = []
    current = ""
    for part in (shlex.quote(a) for a in argv):
        starts_path = part.startswith("/") or part.startswith("'/")
        if current and (len(current) + len(part) + 1 > width or starts_path):
            lines.append(current)
            current = "  " + part
        else:
            current = f"{current} {part}" if current else part
    if current:
        lines.append(current)
    return " \\\n".join(lines)
