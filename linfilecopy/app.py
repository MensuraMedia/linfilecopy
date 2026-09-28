"""Gtk.Application: startup, actions, keyboard shortcuts and window creation."""
from __future__ import annotations

import os
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from linfilecopy import APP_ID, APP_NAME, __version__, paths, resources  # noqa: E402
from linfilecopy.engine import tools  # noqa: E402
from linfilecopy.engine.drives import UDisksClient  # noqa: E402
from linfilecopy.engine.runner import EngineServices, JobRun, RunHooks, RunManager  # noqa: E402
from linfilecopy.model.history import HistoryStore  # noqa: E402
from linfilecopy.model.store import JobStore  # noqa: E402
from linfilecopy.i18n import _  # noqa: E402
from linfilecopy.log import get_logger, setup_logging  # noqa: E402
from linfilecopy.model.settings import AppSettings  # noqa: E402
from linfilecopy.ui.context import AppContext  # noqa: E402
from linfilecopy.ui.manager_theme import ThemeManager  # noqa: E402

_log = get_logger(__name__)

ACCELS: dict[str, list[str]] = {
    "app.new-job": ["<Control>n"],
    "app.save-job": ["<Control>s"],
    "app.start": ["<Control>Return"],
    "app.preview": ["<Control><Shift>p"],
    "app.copy-command": ["<Control><Shift>c"],
    "app.eject": ["<Control>e"],
    "app.shortcuts": ["<Control>question", "<Control>slash"],
    "app.quit": ["<Control>q"],
    **{f"app.page({i})": [f"<Control>{i + 1}"] for i in range(7)},
}


class LinFileCopyApp(Gtk.Application):
    """Single-instance application."""

    def __init__(self) -> None:
        # Tests and screenshots set LFC_NON_UNIQUE so they never hand over to a running copy.
        flags = Gio.ApplicationFlags.NON_UNIQUE if os.environ.get("LFC_NON_UNIQUE") else Gio.ApplicationFlags.FLAGS_NONE
        super().__init__(application_id=APP_ID, flags=flags)
        GLib.set_prgname(APP_ID)          # WM_CLASS: lets the desktop match the window to its menu entry and icon
        from gi.repository import Gdk

        Gdk.set_program_class(APP_ID)     # the class half of WM_CLASS (GTK set it before our code ran)
        GLib.set_application_name(APP_NAME)
        self.ctx: AppContext | None = None
        self.window = None

    # ----- lifecycle -------------------------------------------------------
    def do_startup(self) -> None:  # noqa: D401 - GTK vfunc
        Gtk.Application.do_startup(self)
        paths.ensure_dirs()
        resources.register()
        resources.set_default_window_icon()
        settings = AppSettings.load()
        theme = ThemeManager()
        theme.apply(settings.style, settings.accent)
        self.ctx = ctx = AppContext(settings=settings, theme=theme)
        ctx.jobs = JobStore()
        ctx.history = HistoryStore()
        interrupted = ctx.history.mark_interrupted()
        if interrupted:
            _log.info("marked %d interrupted runs as failed", interrupted)
        self._prune_history()
        udisks = UDisksClient()
        self.engine = EngineServices(history=ctx.history, udisks=udisks, capabilities=None)
        ctx.runs = RunManager(self.engine, RunHooks(
            on_update=lambda run: GLib.idle_add(self._publish_run, "run-updated", run),
            on_finished=lambda run: GLib.idle_add(self._on_run_finished, run),
            request_passphrase=self._request_passphrase,
        ))
        from linfilecopy.ui.manager_drives import DriveManager
        from linfilecopy.ui.manager_notify import NotificationManager

        ctx.drives = DriveManager(ctx, udisks)
        ctx.notifier = NotificationManager(self, ctx)
        self._install_actions()

    def do_activate(self) -> None:
        if self.window is None:
            from linfilecopy.ui.pages import build_pages
            from linfilecopy.ui.window import MainWindow

            assert self.ctx is not None
            self.window = MainWindow(self, self.ctx, build_pages(self.ctx))
            self.ctx.services["window"] = self.window
            self.window.connect("delete-event", self._on_close_request)
            self._detect_tools_async()
            from linfilecopy.ui.manager_tray import TrayManager
            from linfilecopy.ui.manager_triggers import TriggerManager

            self.tray = TrayManager(self, self.ctx)
            self.triggers = TriggerManager(self.ctx)
        self.window.present()

    # ----- closing ------------------------------------------------------------
    def _background_work(self) -> bool:
        """True when closing the window should keep the app alive in the tray."""
        assert self.ctx is not None
        active = bool(self.ctx.runs and [r for r in self.ctx.runs.active() if not r.preview])
        triggers = bool(getattr(self, "triggers", None) and self.triggers.watchers) or any(
            j.triggers.on_drive_connected for j in (self.ctx.jobs.list() if self.ctx.jobs else []))
        return active or triggers

    def _on_close_request(self, win: Gtk.Window, _event: object) -> bool:
        assert self.ctx is not None
        tray = getattr(self, "tray", None)
        if self.ctx.settings.keep_in_tray and tray is not None and tray.available and self._background_work():
            win.hide()
            if not getattr(self, "_held", False):
                self.hold()
                self._held = True
            if self.ctx.notifier is not None:
                self.ctx.notifier.simple("tray", _("LinFileCopy is still running"),
                                         _("Transfers and triggers continue. Open it again from the tray icon."), "misc-info")
            return True
        # Closing for real: always go through _quit so a tray hold and the
        # watchers are released (the app must not linger without a window).
        self._quit()
        return True

    def _confirm_quit(self) -> bool:
        """Ask before quitting with runs in progress. True = quit."""
        assert self.ctx is not None
        active = [r for r in (self.ctx.runs.active() if self.ctx.runs else []) if not r.preview]
        if active:
            from linfilecopy.ui.components.component_dialogs import confirm

            if not confirm(self.window, _("Stop {n} running jobs and quit?").format(n=len(active)),
                           _("Partly copied files are kept and resumed next time."), _("Stop and quit"), destructive=True):
                return False
            self.ctx.runs.cancel_all()
            for r in active:
                r.join(6)
        return True

    def _quit(self) -> None:
        if self._confirm_quit():
            if getattr(self, "triggers", None):
                self.triggers.shutdown()
            if getattr(self, "_held", False):
                self.release()
                self._held = False
            self.quit()

    # ----- tools -------------------------------------------------------------
    def _detect_tools_async(self) -> None:
        def worker() -> None:
            caps = tools.detect()
            GLib.idle_add(self._on_capabilities, caps)

        threading.Thread(target=worker, name="lfc-detect", daemon=True).start()

    def _on_capabilities(self, caps: tools.Capabilities) -> bool:
        assert self.ctx is not None
        self.ctx.capabilities = caps
        self.engine.capabilities = caps
        if not caps.udisks.available:
            self.engine.udisks = None
        self.ctx.publish("capabilities", caps)
        return GLib.SOURCE_REMOVE

    # ----- runs --------------------------------------------------------------------
    def _publish_run(self, topic: str, run: JobRun) -> bool:
        assert self.ctx is not None
        self.ctx.publish(topic, run)
        return GLib.SOURCE_REMOVE

    def _on_run_finished(self, run: JobRun) -> bool:
        assert self.ctx is not None
        self.ctx.publish("run-updated", run)
        self.ctx.publish("run-finished", run)
        self.ctx.publish("history-changed")
        if self.ctx.notifier is not None:
            self.ctx.notifier.run_finished(run)
        if self.ctx.drives is not None and run.job.drive.eject_after:
            self.ctx.drives.refresh()
        return GLib.SOURCE_REMOVE

    def _request_passphrase(self, run: JobRun, drive) -> str | None:  # type: ignore[no-untyped-def]
        from linfilecopy.ui import manager_secrets

        return manager_secrets.request_from_worker(lambda: self.window, drive, run.job.name)

    def _prune_history(self) -> None:
        import os

        assert self.ctx is not None and self.ctx.history is not None
        for path in self.ctx.history.prune(self.ctx.settings.history_days):
            try:
                os.unlink(path)
            except OSError:
                pass

    # ----- actions -------------------------------------------------------------
    def _install_actions(self) -> None:
        simple = {
            "quit": lambda *_: self._quit(),
            "about": self._on_about,
            "shortcuts": self._on_shortcuts,
        }
        for name, cb in simple.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", cb)
            self.add_action(action)
        # Page actions are forwarded to whatever the current page provides.
        for name in ("new-job", "save-job", "start", "preview", "copy-command", "eject"):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", self._forward, name)
            self.add_action(action)
        page = Gio.SimpleAction.new("page", GLib.VariantType.new("i"))
        page.connect("activate", lambda _a, v: self.window and self.window.show_page_index(v.get_int32()))
        self.add_action(page)
        for name, cb in (("show-run", self._on_show_run), ("retry-run", self._on_retry_run),
                         ("open-log", self._on_open_log)):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", cb)
            self.add_action(action)
        preview = Gio.SimpleAction.new_stateful("preview-mode", None, GLib.Variant.new_boolean(False))
        preview.connect("change-state", self._on_preview_mode)
        self.add_action(preview)
        for action_name, accels in ACCELS.items():
            self.set_accels_for_action(action_name, accels)

    def _forward(self, _action: Gio.SimpleAction, _param: object, name: str) -> None:
        assert self.ctx is not None
        self.ctx.publish("action", name)

    def _on_preview_mode(self, action: Gio.SimpleAction, value: GLib.Variant) -> None:
        action.set_state(value)
        assert self.ctx is not None
        self.ctx.preview_mode = value.get_boolean()
        self.ctx.publish("preview-mode", value.get_boolean())

    def _on_show_run(self, _action: Gio.SimpleAction, param: GLib.Variant) -> None:
        self.activate()
        assert self.ctx is not None
        run_id = param.get_string()
        run = self.ctx.runs.get(run_id) if self.ctx.runs else None
        if run is not None and run.active:
            self.window.show_page("transfers")
        else:
            self.window.show_page("history")
            self.ctx.publish("select-run", run_id)

    def _on_retry_run(self, _action: Gio.SimpleAction, param: GLib.Variant) -> None:
        assert self.ctx is not None
        from linfilecopy.model.enums import Trigger

        rec = self.ctx.history.get(param.get_string()) if self.ctx.history else None
        if rec is None:
            return
        job = self.ctx.jobs.get(rec.job_id) if self.ctx.jobs else None
        if job is None:
            from linfilecopy.model.job import SyncJob
            import json

            job = SyncJob.from_dict(json.loads(rec.job_json))
        self.activate()
        from linfilecopy.ui.manager_launch import start_interactive

        start_interactive(self.ctx, job, Trigger.RETRY)

    def _on_open_log(self, _action: Gio.SimpleAction, param: GLib.Variant) -> None:
        assert self.ctx is not None
        rec = self.ctx.history.get(param.get_string()) if self.ctx.history else None
        if rec is not None and rec.log_path:
            from gi.repository import Gio as _Gio

            try:
                _Gio.AppInfo.launch_default_for_uri(_Gio.File.new_for_path(rec.log_path).get_uri(), None)
            except GLib.Error as exc:
                _log.warning("cannot open log: %s", exc.message)

    def _on_about(self, *_args: object) -> None:
        dlg = Gtk.AboutDialog(transient_for=self.window, modal=True)
        dlg.set_program_name(APP_NAME)
        dlg.set_version(__version__)
        dlg.set_comments(_("Copy and sync jobs for local disks and attached drives, powered by rsync."))
        try:
            from gi.repository import GdkPixbuf

            dlg.set_logo(GdkPixbuf.Pixbuf.new_from_file_at_size(str(resources.app_icon_path()), 96, 96))
        except GLib.Error:
            pass
        dlg.set_license_type(Gtk.License.GPL_3_0)
        dlg.set_website("https://github.com/MensuraMedia/linfilecopy")
        dlg.set_credits_section(_("Icons"), ["Phosphor Icons (MIT) https://phosphoricons.com"])
        dlg.connect("response", lambda d, _r: d.destroy())
        dlg.present()

    def _on_shortcuts(self, *_args: object) -> None:
        from linfilecopy.ui.components.component_shortcuts import build_shortcuts_window

        win = build_shortcuts_window()
        win.set_transient_for(self.window)
        win.present()


def run_gui(argv: list[str]) -> int:
    setup_logging()
    app = LinFileCopyApp()
    return app.run([sys.argv[0], *argv])
