"""What each filesystem can store, and how a job adapts to it (#20, CONCEPT §6.3).

The planner looks up the destination filesystem here and drops rsync options
the filesystem cannot honour, reporting each adjustment to the user instead
of letting rsync fail on thousands of files.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from linfilecopy.i18n import _

FAT_MAX_FILE = 4 * 1024**3 - 1
FAT_RESERVED = '"*:<>?\\|'


@dataclass(frozen=True)
class FsCapabilities:
    fs_type: str
    label: str                  # human name, e.g. "exFAT"
    permissions: bool = True    # unix mode bits (and device files)
    owner: bool = True
    symlinks: bool = True
    hardlinks: bool = True
    acl_xattr: bool = True
    coarse_times: bool = False  # compare mtimes within 1 s (--modify-window=1)
    max_file_size: int | None = None
    case_insensitive: bool = False
    reserved_chars: str = ""

    @property
    def full(self) -> bool:
        return self.permissions and self.owner and self.symlinks and self.hardlinks and self.acl_xattr

    def limitations(self) -> list[str]:
        """Short user-facing list of what cannot be stored."""
        out = []
        if not self.permissions:
            out.append(_("permissions"))
        if not self.owner:
            out.append(_("owners"))
        if not self.symlinks:
            out.append(_("symbolic links"))
        if not self.hardlinks:
            out.append(_("hard links"))
        if not self.acl_xattr:
            out.append(_("ACLs and extended attributes"))
        return out

    def summary(self) -> str:
        """One line for the drive list: "everything supported" or what is missing."""
        missing = self.limitations()
        if not missing:
            return _("everything supported")
        if self.max_file_size:
            missing.append(_("files over 4 GB"))
        return _("no {items}").format(items=", ".join(missing))


_FULL = ("ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "jfs", "reiserfs", "bcachefs", "nilfs2", "tmpfs")
_LABELS = {"ext2": "ext2", "ext3": "ext3", "ext4": "ext4", "xfs": "XFS", "btrfs": "Btrfs", "zfs": "ZFS",
           "f2fs": "F2FS", "jfs": "JFS", "reiserfs": "ReiserFS", "bcachefs": "bcachefs", "nilfs2": "NILFS2",
           "tmpfs": "tmpfs", "ntfs": "NTFS", "exfat": "exFAT", "vfat": "FAT32", "hfsplus": "HFS+"}


def capabilities_for(fs_type: str | None) -> FsCapabilities:
    """Capabilities for a filesystem type as reported by UDisks2 or /proc/self/mountinfo."""
    t = (fs_type or "").lower()
    if t in ("ntfs", "ntfs3", "ntfs-3g", "fuseblk"):
        return FsCapabilities("ntfs", "NTFS", permissions=False, owner=False, acl_xattr=False)
    if t == "exfat":
        return FsCapabilities("exfat", "exFAT", permissions=False, owner=False, symlinks=False,
                              hardlinks=False, acl_xattr=False, coarse_times=True, case_insensitive=True,
                              reserved_chars=FAT_RESERVED)
    if t in ("vfat", "fat", "fat32", "fat16", "msdos"):
        return FsCapabilities("vfat", "FAT32", permissions=False, owner=False, symlinks=False,
                              hardlinks=False, acl_xattr=False, coarse_times=True, max_file_size=FAT_MAX_FILE,
                              case_insensitive=True, reserved_chars=FAT_RESERVED)
    if t == "hfsplus":
        return FsCapabilities("hfsplus", "HFS+", acl_xattr=False, case_insensitive=True)
    return FsCapabilities(t or "unknown", _LABELS.get(t, t or _("unknown")))


# ---------------------------------------------------------------------------
# /proc/self/mountinfo: filesystem type of any path, even without UDisks2

@dataclass(frozen=True)
class MountEntry:
    mount_point: str
    fs_type: str
    source: str


def _unescape(field: str) -> str:
    # mountinfo escapes space, tab, newline and backslash as octal \040 etc.
    out, i = [], 0
    while i < len(field):
        if field[i] == "\\" and i + 3 < len(field) and field[i + 1:i + 4].isdigit():
            out.append(chr(int(field[i + 1:i + 4], 8)))
            i += 4
        else:
            out.append(field[i])
            i += 1
    return "".join(out)


def parse_mountinfo(text: str) -> list[MountEntry]:
    entries = []
    for line in text.splitlines():
        parts = line.split(" - ", 1)
        if len(parts) != 2:
            continue
        left, right = parts[0].split(), parts[1].split()
        if len(left) < 5 or len(right) < 2:
            continue
        entries.append(MountEntry(_unescape(left[4]), right[0], _unescape(right[1])))
    return entries


def read_mounts() -> list[MountEntry]:
    try:
        with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as fh:
            return parse_mountinfo(fh.read())
    except OSError:
        return []


def mount_for_path(path: str, mounts: list[MountEntry] | None = None) -> MountEntry | None:
    """The mount containing ``path`` (longest matching mount point). Path need not exist yet."""
    mounts = read_mounts() if mounts is None else mounts
    path = os.path.normpath(os.path.abspath(path))
    best: MountEntry | None = None
    for m in mounts:
        mp = m.mount_point.rstrip("/") or "/"
        if path == mp or path.startswith(mp.rstrip("/") + "/") or mp == "/":
            if best is None or len(mp) >= len(best.mount_point.rstrip("/") or "/"):
                best = m
    return best


def fs_type_for_path(path: str, mounts: list[MountEntry] | None = None) -> str | None:
    m = mount_for_path(path, mounts)
    return m.fs_type if m else None
