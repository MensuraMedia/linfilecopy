"""Drive discovery and control through UDisks2 over D-Bus (#10, #20).

``parse_managed_objects`` is pure (tested with recorded data). ``UDisksClient``
performs blocking D-Bus calls and must be used from worker threads; the UI
wraps it. Jobs identify drives by filesystem UUID so a drive that mounts at a
different path next time is still found.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from linfilecopy.engine.filesystems import FsCapabilities, capabilities_for
from linfilecopy.i18n import _
from linfilecopy.log import get_logger
from linfilecopy.model.enums import DriveKind
from linfilecopy.model.job import Endpoint

_log = get_logger(__name__)

UD = "org.freedesktop.UDisks2"
BLOCK = f"{UD}.Block"
FILESYSTEM = f"{UD}.Filesystem"
ENCRYPTED = f"{UD}.Encrypted"
DRIVE = f"{UD}.Drive"
MDRAID = f"{UD}.MDRaid"
HIDDEN_MOUNTS = {"/boot", "/boot/efi", "/efi"}


class DriveError(Exception):
    """A drive operation failed; ``str(exc)`` is user-facing."""


@dataclass(frozen=True)
class DriveInfo:
    """One filesystem-bearing (or encrypted) block device."""

    object_path: str
    device: str
    uuid: str
    label: str                 # display name
    fs_type: str
    size: int
    mount_points: tuple[str, ...] = ()
    kind: DriveKind = DriveKind.INTERNAL
    encrypted: bool = False    # this block is a LUKS container
    locked: bool = False       # container with no cleartext device
    container_uuid: str | None = None   # for a cleartext fs: the LUKS container's UUID
    cleartext_path: str | None = None   # for a container: its unlocked block
    drive_path: str | None = None
    drive_model: str = ""
    can_power_off: bool = False
    ejectable: bool = False
    system: bool = False       # boot/EFI/swap: hidden unless asked
    free: int | None = None    # filled by with_free_space()
    array_level: str = ""

    @property
    def mount_point(self) -> str | None:
        return self.mount_points[0] if self.mount_points else None

    @property
    def mounted(self) -> bool:
        return bool(self.mount_points)

    @property
    def fs(self) -> FsCapabilities:
        return capabilities_for(self.fs_type)

    def describe(self) -> str:
        """e.g. "USB · exFAT · 41.3 GB free" (no formatting library in the engine)."""
        from linfilecopy.formatting import format_bytes

        parts = [
            {DriveKind.REMOVABLE: _("Removable"), DriveKind.ARRAY: _("Storage array"),
             DriveKind.INTERNAL: _("Internal")}.get(self.kind, _("Drive")),
        ]
        if self.array_level:
            parts.append(self.array_level.upper().replace("RAID", "RAID "))
        if self.encrypted:
            parts.append(_("LUKS · locked") if self.locked else "LUKS")
        else:
            parts.append(self.fs.label)
        if self.free is not None:
            parts.append(_("{size} free").format(size=format_bytes(self.free)))
        elif not self.mounted and not self.locked:
            parts.append(_("not mounted"))
        return " · ".join(parts)


def _bytestring(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    elif isinstance(value, (list, tuple)):
        raw = bytes(value)
    else:
        return str(value or "")
    return raw.rstrip(b"\0").decode("utf-8", "replace")


def _size_label(size: int) -> str:
    """GNOME-style name for an unlabelled volume: "62 GB Volume"."""
    gb = size / 1000**3
    if gb >= 1000:
        return _("{n:.0f} TB Volume").format(n=gb / 1000)
    return _("{n:.0f} GB Volume").format(n=gb) if gb >= 1 else _("{n:.0f} MB Volume").format(n=size / 1000**2)


def _mount_name(mp: str) -> str:
    if mp == "/":
        return _("System")
    if mp == "/home":
        return _("Home")
    return os.path.basename(mp.rstrip("/")) or mp


def parse_managed_objects(objects: dict[str, dict[str, dict[str, Any]]]) -> list[DriveInfo]:
    """Turn ``ObjectManager.GetManagedObjects`` output into DriveInfo records."""
    drives: dict[str, dict[str, Any]] = {p: i[DRIVE] for p, i in objects.items() if DRIVE in i}
    raids: dict[str, dict[str, Any]] = {p: i[MDRAID] for p, i in objects.items() if MDRAID in i}
    blocks: dict[str, dict[str, Any]] = {p: i for p, i in objects.items() if BLOCK in i}
    out: list[DriveInfo] = []
    for path, ifaces in blocks.items():
        b = ifaces[BLOCK]
        usage = b.get("IdUsage", "")
        is_fs = FILESYSTEM in ifaces
        is_crypt = ENCRYPTED in ifaces
        if not (is_fs or is_crypt) or usage not in ("filesystem", "crypto"):
            continue
        device = _bytestring(b.get("Device"))
        if os.path.basename(device).startswith(("loop", "ram", "zram")):
            continue

        # Walk from a cleartext device to its container to find the physical drive.
        drive_path = b.get("Drive") or "/"
        backing = b.get("CryptoBackingDevice") or "/"
        container_uuid = None
        if backing != "/" and backing in blocks:
            parent = blocks[backing][BLOCK]
            container_uuid = parent.get("IdUUID") or None
            if drive_path == "/":
                drive_path = parent.get("Drive") or "/"
        drive = drives.get(drive_path, {})
        raid_path = b.get("MDRaid") or "/"
        if raid_path == "/" and backing in blocks:
            raid_path = blocks[backing][BLOCK].get("MDRaid") or "/"
        raid = raids.get(raid_path)

        if raid is not None:
            kind = DriveKind.ARRAY
        elif drive.get("Removable") or drive.get("Ejectable") or drive.get("ConnectionBus") in ("usb", "sdio", "ieee1394"):
            kind = DriveKind.REMOVABLE
        else:
            kind = DriveKind.INTERNAL

        mount_points: tuple[str, ...] = ()
        if is_fs:
            mount_points = tuple(_bytestring(m) for m in ifaces[FILESYSTEM].get("MountPoints", []))
        size = int(b.get("Size", 0))
        label = b.get("IdLabel") or b.get("HintName") or ""
        if not label and raid is not None:
            label = raid.get("Name", "").split(":")[-1]
        if not label and mount_points and kind is DriveKind.INTERNAL:
            label = _mount_name(mount_points[0])
        if not label:
            label = _size_label(size)

        cleartext = None
        locked = False
        if is_crypt:
            ct = ifaces[ENCRYPTED].get("CleartextDevice") or "/"
            cleartext = None if ct == "/" else ct
            locked = cleartext is None
        system = bool(b.get("HintIgnore")) or any(m in HIDDEN_MOUNTS for m in mount_points)

        out.append(DriveInfo(
            object_path=path, device=device, uuid=b.get("IdUUID", ""), label=label,
            fs_type=b.get("IdType", ""), size=size, mount_points=mount_points, kind=kind,
            encrypted=is_crypt, locked=locked, container_uuid=container_uuid, cleartext_path=cleartext,
            drive_path=None if drive_path == "/" else drive_path,
            drive_model=" ".join(x for x in (drive.get("Vendor", "").strip(), drive.get("Model", "").strip()) if x),
            can_power_off=bool(drive.get("CanPowerOff")), ejectable=bool(drive.get("Ejectable")),
            system=system, array_level=(raid or {}).get("Level", ""),
        ))
    # Unlocked containers are represented by their cleartext filesystem; hide the container.
    unlocked_containers = {d.object_path for d in out if d.encrypted and not d.locked}
    out = [d for d in out if d.object_path not in unlocked_containers]
    order = {DriveKind.INTERNAL: 0, DriveKind.REMOVABLE: 1, DriveKind.ARRAY: 2, DriveKind.UNKNOWN: 3}
    out.sort(key=lambda d: (order[d.kind], d.mount_point != "/", d.mount_point != "/home", d.label.lower()))
    return out


def with_free_space(drive: DriveInfo) -> DriveInfo:
    if not drive.mount_point:
        return drive
    try:
        st = os.statvfs(drive.mount_point)
        return replace(drive, free=st.f_bavail * st.f_frsize)
    except OSError:
        return drive


def visible_drives(drives: list[DriveInfo], show_system: bool = False) -> list[DriveInfo]:
    return [d for d in drives if show_system or not d.system]


# ---------------------------------------------------------------------------
# endpoints <-> drives

class EndpointState(Enum):
    READY = "ready"            # path usable now
    NOT_MOUNTED = "not_mounted"
    LOCKED = "locked"
    MISSING = "missing"        # drive not connected


@dataclass(frozen=True)
class ResolvedEndpoint:
    path: str
    state: EndpointState
    drive: DriveInfo | None = None
    container: DriveInfo | None = None   # locked LUKS container to unlock


def find_by_uuid(drives: list[DriveInfo], uuid: str) -> DriveInfo | None:
    return next((d for d in drives if d.uuid == uuid), None)


def resolve_endpoint(ep: Endpoint, drives: list[DriveInfo]) -> ResolvedEndpoint:
    """Current absolute path of an endpoint, following its drive's UUID."""
    if not ep.volume_uuid:
        return ResolvedEndpoint(ep.path, EndpointState.READY)
    drive = find_by_uuid(drives, ep.volume_uuid)
    if drive is None:
        container = None
        if ep.container_uuid:
            container = find_by_uuid(drives, ep.container_uuid)
        if container is not None and container.locked:
            return ResolvedEndpoint(ep.path, EndpointState.LOCKED, None, container)
        return ResolvedEndpoint(ep.path, EndpointState.MISSING)
    if not drive.mounted:
        return ResolvedEndpoint(ep.path, EndpointState.NOT_MOUNTED, drive)
    rel = ep.relative_path or ""
    path = os.path.normpath(os.path.join(drive.mount_point or "/", rel)) if rel else drive.mount_point or ep.path
    return ResolvedEndpoint(path, EndpointState.READY, drive)


def endpoint_for_path(path: str, drives: list[DriveInfo]) -> Endpoint:
    """Describe a chosen folder: which drive it is on and where inside that drive."""
    path = os.path.normpath(path)
    best: DriveInfo | None = None
    for d in drives:
        for mp in d.mount_points:
            if path == mp or path.startswith(mp.rstrip("/") + "/"):
                if best is None or len(mp) > len(best.mount_point or ""):
                    best = d
    if best is None or best.mount_point == "/":
        from linfilecopy.engine.filesystems import fs_type_for_path

        return Endpoint(path=path, kind=DriveKind.INTERNAL if best else DriveKind.UNKNOWN,
                        fs_type=(best.fs_type if best else fs_type_for_path(path)),
                        volume_label=best.label if best else None)
    mp = best.mount_point or "/"
    rel = os.path.relpath(path, mp)
    return Endpoint(path=path, volume_uuid=best.uuid or None, volume_label=best.label,
                    relative_path="" if rel == "." else rel, kind=best.kind, fs_type=best.fs_type,
                    container_uuid=best.container_uuid)


# ---------------------------------------------------------------------------
# D-Bus client (blocking; call from worker threads)

@dataclass
class UDisksClient:
    """Thin blocking wrapper over the UDisks2 D-Bus API."""

    timeout_ms: int = 25000
    _bus: Any = field(default=None, repr=False)

    def _conn(self) -> Any:
        if self._bus is None:
            from gi.repository import Gio

            self._bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        return self._bus

    def _call(self, path: str, iface: str, method: str, args: Any, reply: str | None = None) -> Any:
        from gi.repository import Gio, GLib

        try:
            res = self._conn().call_sync(
                UD, path, iface, method, args, GLib.VariantType.new(reply) if reply else None,
                Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, self.timeout_ms, None,
            )
        except GLib.Error as exc:
            raise DriveError(_friendly(exc.message)) from exc
        return res.unpack() if res is not None else None

    def list_drives(self) -> list[DriveInfo]:
        objs = self._call("/org/freedesktop/UDisks2", "org.freedesktop.DBus.ObjectManager",
                          "GetManagedObjects", None, "(a{oa{sa{sv}}})")[0]
        return [with_free_space(d) for d in parse_managed_objects(objs)]

    def mount(self, drive: DriveInfo) -> str:
        from gi.repository import GLib

        return self._call(drive.object_path, FILESYSTEM, "Mount", GLib.Variant("(a{sv})", ({},)), "(s)")[0]

    def unmount(self, drive: DriveInfo) -> None:
        from gi.repository import GLib

        self._call(drive.object_path, FILESYSTEM, "Unmount", GLib.Variant("(a{sv})", ({},)))

    def unlock(self, container: DriveInfo, passphrase: str) -> str:
        """Unlock a LUKS container; returns the cleartext block's object path."""
        from gi.repository import GLib

        return self._call(container.object_path, ENCRYPTED, "Unlock",
                          GLib.Variant("(sa{sv})", (passphrase, {})), "(o)")[0]

    def lock(self, container_path: str) -> None:
        from gi.repository import GLib

        self._call(container_path, ENCRYPTED, "Lock", GLib.Variant("(a{sv})", ({},)))

    def power_off(self, drive: DriveInfo) -> None:
        """Safely remove: power off the whole drive (falls back to eject)."""
        from gi.repository import GLib

        if not drive.drive_path:
            raise DriveError(_("This drive cannot be removed safely from here."))
        method = "PowerOff" if drive.can_power_off else "Eject"
        self._call(drive.drive_path, DRIVE, method, GLib.Variant("(a{sv})", ({},)))


def _friendly(message: str) -> str:
    m = message or ""
    low = m.lower()
    if "not authorized" in low or "notauthorized" in low:
        return _("You are not allowed to do this. The system refused the request.")
    if "target is busy" in low or "device is busy" in low:
        return _("The drive is busy. Close any files or windows using it and try again.")
    if "wrong passphrase" in low or "no key available" in low or "failed to activate" in low:
        return _("The passphrase is wrong.")
    if "already mounted" in low:
        return _("The drive is already mounted.")
    if "no such object" in low or "unknownobject" in low:
        return _("The drive is no longer connected.")
    return m.split(": ", 1)[-1] if m else _("The drive operation failed.")
