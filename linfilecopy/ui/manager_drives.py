"""Keeps the list of drives current: UDisks2 signals trigger a background refresh."""
from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib  # noqa: E402

from linfilecopy.engine.drives import DriveError, DriveInfo, UDisksClient  # noqa: E402
from linfilecopy.log import get_logger  # noqa: E402
from linfilecopy.ui.context import AppContext  # noqa: E402

_log = get_logger(__name__)
REFRESH_DEBOUNCE_MS = 400
FREE_SPACE_POLL_S = 60


class DriveManager:
    """Publishes ``("drives", list[DriveInfo])`` on the context whenever drives change."""

    def __init__(self, ctx: AppContext, client: UDisksClient | None) -> None:
        self.ctx = ctx
        self.client = client
        self.drives: list[DriveInfo] = []
        self._pending: int | None = None
        self._refreshing = False
        self._again = False
        self._subs: list[int] = []
        self._bus = None
        if client is not None:
            try:
                self._bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
                for member in ("InterfacesAdded", "InterfacesRemoved"):
                    self._subs.append(self._bus.signal_subscribe(
                        "org.freedesktop.UDisks2", "org.freedesktop.DBus.ObjectManager", member,
                        "/org/freedesktop/UDisks2", None, Gio.DBusSignalFlags.NONE, self._on_signal))
                # Mount/unmount and lock/unlock show up as property changes.
                self._subs.append(self._bus.signal_subscribe(
                    "org.freedesktop.UDisks2", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                    None, None, Gio.DBusSignalFlags.NONE, self._on_signal))
            except GLib.Error as exc:
                _log.warning("cannot watch UDisks2: %s", exc.message)
        GLib.timeout_add_seconds(FREE_SPACE_POLL_S, self._poll)
        self.refresh()

    def _on_signal(self, *_args: object) -> None:
        if self._pending is None:
            self._pending = GLib.timeout_add(REFRESH_DEBOUNCE_MS, self._debounced)

    def _debounced(self) -> bool:
        self._pending = None
        self.refresh()
        return GLib.SOURCE_REMOVE

    def _poll(self) -> bool:
        self.refresh()
        return GLib.SOURCE_CONTINUE

    def refresh(self) -> None:
        """Re-read drives on a worker thread; publishes on the main thread."""
        if self.client is None:
            GLib.idle_add(self._publish, [])
            return
        if self._refreshing:
            self._again = True
            return
        self._refreshing = True

        def worker() -> None:
            try:
                drives = self.client.list_drives()
            except DriveError as exc:
                _log.warning("drive refresh failed: %s", exc)
                drives = self.drives
            GLib.idle_add(self._publish, drives)

        threading.Thread(target=worker, name="lfc-drives", daemon=True).start()

    def _publish(self, drives: list[DriveInfo]) -> bool:
        self._refreshing = False
        changed = drives != self.drives
        self.drives = drives
        if changed:
            self.ctx.publish("drives", drives)
        if self._again:
            self._again = False
            self.refresh()
        return GLib.SOURCE_REMOVE

    # ----- actions (run in a worker, report on the main thread) -----------------
    def run_action(self, label: str, func, on_done=None) -> None:  # type: ignore[no-untyped-def]
        """Run a blocking drive operation off the main thread."""

        def worker() -> None:
            error = None
            try:
                func()
            except DriveError as exc:
                error = str(exc)
            try:   # read the new state here so on_done sees the fresh mount points
                drives = self.client.list_drives() if self.client else []
            except DriveError:
                drives = self.drives
            GLib.idle_add(self._action_done, label, error, on_done, drives)

        threading.Thread(target=worker, name="lfc-drive-action", daemon=True).start()

    def _action_done(self, label: str, error: str | None, on_done, drives: list[DriveInfo]) -> bool:  # type: ignore[no-untyped-def]
        self._refreshing = False
        self._publish(drives)
        if on_done:
            on_done(error)          # the caller reports its own errors
        else:
            self.ctx.publish("drive-action", label, error)
        return GLib.SOURCE_REMOVE

    def eject(self, drive: DriveInfo) -> None:
        assert self.client is not None
        client = self.client

        def do() -> None:
            import os

            os.sync()
            if drive.mounted:
                client.unmount(drive)
            client.power_off(drive)

        self.run_action(drive.label, do)

    def mount(self, drive: DriveInfo, on_done=None) -> None:  # type: ignore[no-untyped-def]
        assert self.client is not None
        self.run_action(drive.label, lambda: self.client.mount(drive), on_done)

    def unlock(self, container: DriveInfo, passphrase: str, on_done=None) -> None:  # type: ignore[no-untyped-def]
        assert self.client is not None
        client = self.client

        def do() -> None:
            client.unlock(container, passphrase)
            for d in client.list_drives():
                if d.container_uuid == container.uuid and not d.mounted:
                    client.mount(d)

        self.run_action(container.label, do, on_done)
