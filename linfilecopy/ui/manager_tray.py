"""Tray icon via Ayatana AppIndicator (optional). The app stays usable without it."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from linfilecopy import resources  # noqa: E402
from linfilecopy.engine.drives import visible_drives  # noqa: E402
from linfilecopy.engine.runner import JobRun  # noqa: E402
from linfilecopy.i18n import _, ngettext  # noqa: E402
from linfilecopy.log import get_logger  # noqa: E402
from linfilecopy.model.enums import DriveKind, RunStatus  # noqa: E402
from linfilecopy.paths import DATA_DIR  # noqa: E402
from linfilecopy.ui.context import AppContext  # noqa: E402

_log = get_logger(__name__)


def _indicator_module():  # type: ignore[no-untyped-def]
    for name in ("AyatanaAppIndicator3", "AppIndicator3"):
        try:
            gi.require_version(name, "0.1")
            return __import__(f"gi.repository.{name}", fromlist=[name])
        except (ImportError, ValueError):
            continue
    return None


class TrayManager:
    """Menu: Show, status line, Pause/Resume all, Eject removable drives, Quit."""

    def __init__(self, app: Gtk.Application, ctx: AppContext) -> None:
        self.app = app
        self.ctx = ctx
        self.indicator = None
        mod = _indicator_module()
        if mod is None:
            return
        icon_dir = str(DATA_DIR / resources.ICON_SUBDIR)
        self.indicator = mod.Indicator.new("linfilecopy", "lfc-action-duplicate-symbolic",
                                           mod.IndicatorCategory.APPLICATION_STATUS)
        self.indicator.set_icon_theme_path(icon_dir)
        self.indicator.set_title("LinFileCopy")
        self.indicator.set_status(mod.IndicatorStatus.ACTIVE)
        self._mod = mod
        self._rebuild_pending = False
        self.rebuild()
        ctx.subscribe("run-updated", lambda _r: self._queue_rebuild())
        ctx.subscribe("drives", lambda _d: self._queue_rebuild())

    @property
    def available(self) -> bool:
        return self.indicator is not None

    def _queue_rebuild(self) -> None:
        if self.indicator is not None and not self._rebuild_pending:
            self._rebuild_pending = True
            GLib.timeout_add(1000, self._do_rebuild)

    def _do_rebuild(self) -> bool:
        self._rebuild_pending = False
        self.rebuild()
        return GLib.SOURCE_REMOVE

    def rebuild(self) -> None:
        if self.indicator is None:
            return
        menu = Gtk.Menu()

        def item(text: str, cb=None, sensitive: bool = True) -> None:  # type: ignore[no-untyped-def]
            mi = Gtk.MenuItem(label=text)
            mi.set_sensitive(sensitive)
            if cb:
                mi.connect("activate", lambda *_a: cb())
            menu.append(mi)

        item(_("Show LinFileCopy"), self.show_window)
        menu.append(Gtk.SeparatorMenuItem())
        runs: list[JobRun] = [r for r in (self.ctx.runs.active() if self.ctx.runs else []) if not r.preview]
        if runs:
            running = [r for r in runs if r.status is RunStatus.RUNNING]
            text = ngettext("{n} running", "{n} running", len(runs)).format(n=len(runs))
            if len(running) == 1:
                text += f" ({running[0].snapshot.percent}%)"
            item(text, sensitive=False)
            if any(r.status is RunStatus.PAUSED for r in runs):
                item(_("Resume all"), lambda: [r.resume() for r in runs])
            else:
                item(_("Pause all"), lambda: self.ctx.runs.pause_all() if self.ctx.runs else None)
        else:
            item(_("Nothing running"), sensitive=False)
        drives = [d for d in visible_drives(self.ctx.drives.drives if self.ctx.drives else [])
                  if d.kind is DriveKind.REMOVABLE and d.mounted]
        if drives:
            menu.append(Gtk.SeparatorMenuItem())
            for d in drives:
                item(_("Eject {drive}").format(drive=d.label), lambda d=d: self.ctx.drives.eject(d))
        menu.append(Gtk.SeparatorMenuItem())
        item(_("Quit"), lambda: self.app.activate_action("quit", None))
        menu.show_all()
        self.indicator.set_menu(menu)

    def show_window(self) -> None:
        self.app.activate()
