"""Gtk.Application: startup, actions, keyboard shortcuts and window creation."""
from __future__ import annotations

import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from linfilecopy import APP_ID, APP_NAME, __version__, paths, resources  # noqa: E402
from linfilecopy.engine import tools  # noqa: E402
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
    **{f"app.page({i})": [f"<Control>{i + 1}"] for i in range(6)},
}


class LinFileCopyApp(Gtk.Application):
    """Single-instance application."""

    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        GLib.set_application_name(APP_NAME)
        self.ctx: AppContext | None = None
        self.window = None

    # ----- lifecycle -------------------------------------------------------
    def do_startup(self) -> None:  # noqa: D401 - GTK vfunc
        Gtk.Application.do_startup(self)
        paths.ensure_dirs()
        resources.register()
        settings = AppSettings.load()
        theme = ThemeManager()
        theme.apply(settings.style, settings.accent)
        self.ctx = AppContext(settings=settings, theme=theme)
        self._install_actions()

    def do_activate(self) -> None:
        if self.window is None:
            from linfilecopy.ui.pages import build_pages
            from linfilecopy.ui.window import MainWindow

            assert self.ctx is not None
            self.window = MainWindow(self, self.ctx, build_pages(self.ctx))
            self.ctx.services["window"] = self.window
            self._detect_tools_async()
        self.window.present()

    # ----- tools -------------------------------------------------------------
    def _detect_tools_async(self) -> None:
        def worker() -> None:
            caps = tools.detect()
            GLib.idle_add(self._on_capabilities, caps)

        threading.Thread(target=worker, name="lfc-detect", daemon=True).start()

    def _on_capabilities(self, caps: tools.Capabilities) -> bool:
        assert self.ctx is not None
        self.ctx.capabilities = caps
        self.ctx.publish("capabilities", caps)
        return GLib.SOURCE_REMOVE

    # ----- actions -------------------------------------------------------------
    def _install_actions(self) -> None:
        simple = {
            "quit": lambda *_: self.quit(),
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
        self.ctx.services["preview_mode"] = value.get_boolean()
        self.ctx.publish("preview-mode", value.get_boolean())

    def _on_about(self, *_args: object) -> None:
        dlg = Gtk.AboutDialog(transient_for=self.window, modal=True)
        dlg.set_program_name(APP_NAME)
        dlg.set_version(__version__)
        dlg.set_comments(_("Copy and sync jobs for local disks and attached drives, powered by rsync."))
        dlg.set_logo_icon_name("io.github.mensuramedia.LinFileCopy")
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
