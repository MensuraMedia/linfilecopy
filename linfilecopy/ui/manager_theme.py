"""Light/dark handling and accent colour.

"system" follows the desktop colour-scheme via the XDG settings portal (live),
falling back to the GTK theme name. The dark token file is loaded whenever the
effective theme background is dark, whatever GTK theme the user runs.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from linfilecopy import resources  # noqa: E402
from linfilecopy.log import get_logger  # noqa: E402
from linfilecopy.model.settings import ACCENTS  # noqa: E402

_log = get_logger(__name__)
PORTAL_NS = "org.freedesktop.appearance"


class ThemeManager:
    """Applies style (system/light/dark) and accent colour to the whole app."""

    def __init__(self) -> None:
        self._base = resources.load_css("style.css")
        self._dark = resources.load_css("style-dark.css")
        self._accent = Gtk.CssProvider()
        self._dark_loaded = False
        self._style = "system"
        self._portal_prefers_dark: bool | None = None
        resources.add_provider(self._base)
        resources.add_provider(self._accent, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self._connect_portal()
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.connect("notify::gtk-theme-name", lambda *_: self._refresh())

    # ----- public --------------------------------------------------------
    def apply(self, style: str, accent: str) -> None:
        self._style = style
        colour = ACCENTS.get(accent, ACCENTS["blue"])
        self._accent.load_from_data(f"@define-color lfc_accent {colour};".encode())
        self._refresh()

    @property
    def is_dark(self) -> bool:
        return self._dark_loaded

    # ----- internals -----------------------------------------------------
    def _wants_dark(self) -> bool:
        if self._style == "dark":
            return True
        if self._style == "light":
            return False
        if self._portal_prefers_dark is not None:
            return self._portal_prefers_dark
        settings = Gtk.Settings.get_default()
        name = (settings.props.gtk_theme_name or "").lower() if settings else ""
        return name.endswith("-dark") or ":dark" in name

    def _refresh(self) -> None:
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.props.gtk_application_prefer_dark_theme = self._wants_dark()
        # Decide from the colour actually in effect so any GTK theme works.
        dark = self._background_is_dark()
        if dark and not self._dark_loaded:
            resources.add_provider(self._dark, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        elif not dark and self._dark_loaded:
            resources.remove_provider(self._dark)
        self._dark_loaded = dark

    @staticmethod
    def _background_is_dark() -> bool:
        probe = Gtk.Window()
        ctx = probe.get_style_context()
        found, colour = ctx.lookup_color("theme_bg_color")
        probe.destroy()
        if not found:
            return False
        luminance = 0.2126 * colour.red + 0.7152 * colour.green + 0.0722 * colour.blue
        return luminance < 0.5

    def _connect_portal(self) -> None:
        def on_proxy(_src: object, result: Gio.AsyncResult) -> None:
            try:
                proxy = Gio.DBusProxy.new_for_bus_finish(result)
            except GLib.Error:
                return
            proxy.call("ReadOne", GLib.Variant("(ss)", (PORTAL_NS, "color-scheme")),
                       Gio.DBusCallFlags.NONE, 1000, None, on_read)
            proxy.connect("g-signal", on_signal)

        def on_read(proxy: Gio.DBusProxy, result: Gio.AsyncResult) -> None:
            try:
                value = proxy.call_finish(result).unpack()[0]
            except GLib.Error:
                return
            self._set_portal_value(value)

        def on_signal(_proxy: Gio.DBusProxy, _sender: str, signal: str, params: GLib.Variant) -> None:
            if signal == "SettingChanged":
                ns, key, value = params.unpack()
                if ns == PORTAL_NS and key == "color-scheme":
                    self._set_portal_value(value)

        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES, None,
            "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Settings", None, on_proxy,
        )

    def _set_portal_value(self, value: object) -> None:
        # 0 = no preference, 1 = prefer dark, 2 = prefer light
        self._portal_prefers_dark = {1: True, 2: False}.get(value if isinstance(value, int) else -1)
        _log.debug("portal colour-scheme=%s", value)
        self._refresh()
