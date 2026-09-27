"""Detection of the system tools and optional libraries LinFileCopy relies on.

Nothing here imports Gtk. Detection is cheap (a few ``--version`` calls) but
still runs on a worker thread from the UI. Every probe is injectable so the
logic can be unit-tested without the real tools.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable

from linfilecopy.i18n import _

Which = Callable[[str], "str | None"]
Runner = Callable[[list[str]], str]

RSYNC_VERSION_RE = re.compile(r"rsync\s+version\s+v?(\d+)\.(\d+)\.(\d+)")

INSTALL_HINTS: dict[str, dict[str, str]] = {
    "rsync": {
        "Debian / Ubuntu": "sudo apt install rsync",
        "Fedora": "sudo dnf install rsync",
        "Arch": "sudo pacman -S rsync",
        "openSUSE": "sudo zypper install rsync",
    },
    "udisks2": {
        "Debian / Ubuntu": "sudo apt install udisks2",
        "Fedora": "sudo dnf install udisks2",
        "Arch": "sudo pacman -S udisks2",
        "openSUSE": "sudo zypper install udisks2",
    },
}


def _run_text(argv: list[str]) -> str:
    """Run a short probe command and return its stdout ('' on any failure)."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout


@dataclass(frozen=True)
class ToolStatus:
    """Result of probing one tool or library."""

    name: str
    available: bool
    path: str | None = None
    version: str | None = None
    purpose: str = ""
    missing_effect: str = ""
    install: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Capabilities:
    """Everything the planner and UI need to know about the environment."""

    rsync: ToolStatus
    ionice: ToolStatus
    nice: ToolStatus
    udisks: ToolStatus
    systemd_user: ToolStatus
    crontab: ToolStatus
    appindicator: ToolStatus
    secret: ToolStatus
    rsync_version: tuple[int, int, int] | None = None

    @property
    def can_run(self) -> bool:
        """True when jobs can be executed at all."""
        return self.rsync.available and self.rsync_version is not None and self.rsync_version >= (3, 1, 0)

    def rsync_at_least(self, *version: int) -> bool:
        return self.rsync_version is not None and self.rsync_version >= tuple(version)

    def all(self) -> list[ToolStatus]:
        return [
            self.rsync, self.udisks, self.ionice, self.nice,
            self.systemd_user, self.crontab, self.appindicator, self.secret,
        ]


def parse_rsync_version(text: str) -> tuple[int, int, int] | None:
    """Extract ``(major, minor, patch)`` from ``rsync --version`` output."""
    m = RSYNC_VERSION_RE.search(text)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _gi_available(namespace: str, version: str) -> bool:
    try:
        import gi

        gi.require_version(namespace, version)
        __import__(f"gi.repository.{namespace}")
        return True
    except (ImportError, ValueError):
        return False


def _udisks_available() -> bool:
    """True when the UDisks2 service answers on the system bus."""
    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        bus.call_sync(
            "org.freedesktop.UDisks2", "/org/freedesktop/UDisks2/Manager",
            "org.freedesktop.DBus.Properties", "Get",
            GLib.Variant("(ss)", ("org.freedesktop.UDisks2.Manager", "Version")),
            None, Gio.DBusCallFlags.NONE, 2000, None,
        )
        return True
    except Exception:  # noqa: BLE001 - any D-Bus failure means "not available"
        return False


def detect(
    which: Which = shutil.which,
    run: Runner = _run_text,
    udisks_probe: Callable[[], bool] = _udisks_available,
    gi_probe: Callable[[str, str], bool] = _gi_available,
) -> Capabilities:
    """Probe the environment and return its :class:`Capabilities`."""
    rsync_path = which("rsync")
    version = parse_rsync_version(run([rsync_path, "--version"])) if rsync_path else None
    rsync = ToolStatus(
        "rsync", bool(rsync_path and version), rsync_path,
        ".".join(map(str, version)) if version else None,
        _("Copy engine"), _("Jobs cannot run until rsync is installed."), INSTALL_HINTS["rsync"],
    )
    if version is not None and version < (3, 1, 0):
        rsync = ToolStatus(
            "rsync", False, rsync_path, ".".join(map(str, version)), _("Copy engine"),
            _("rsync 3.1.0 or newer is required for progress reporting."), INSTALL_HINTS["rsync"],
        )

    def simple(name: str, purpose: str, effect: str) -> ToolStatus:
        path = which(name)
        return ToolStatus(name, bool(path), path, None, purpose, effect)

    systemctl = which("systemctl")
    # show-environment only succeeds when a user service manager is reachable.
    systemd_ok = bool(systemctl) and bool(run([systemctl, "--user", "show-environment"]).strip())
    return Capabilities(
        rsync=rsync,
        ionice=simple("ionice", _("Background priority"), _("Background priority is unavailable.")),
        nice=simple("nice", _("Background priority"), _("Background priority is unavailable.")),
        udisks=ToolStatus(
            "udisks2", udisks_probe(), None, None, _("Mount, unlock and eject drives"),
            _("Drives must be mounted by hand; unlock and eject are unavailable."), INSTALL_HINTS["udisks2"],
        ),
        systemd_user=ToolStatus(
            "systemd --user", systemd_ok, systemctl, None, _("Scheduled runs"),
            _("Schedules fall back to crontab."),
        ),
        crontab=simple("crontab", _("Scheduled runs (fallback)"), _("Only systemd timers can be used.")),
        appindicator=ToolStatus(
            "AyatanaAppIndicator3", gi_probe("AyatanaAppIndicator3", "0.1"), None, None,
            _("Tray icon"), _("No tray icon; triggers work only while the window is open."),
        ),
        secret=ToolStatus(
            "libsecret", gi_probe("Secret", "1"), None, None, _("Remember drive passphrases"),
            _("Passphrases are asked for on every run."),
        ),
        rsync_version=version,
    )
