"""Register bundled icons and CSS with GTK.

Installed builds ship ``data/linfilecopy.gresource``. When running from a
source checkout without the compiled bundle, the same files are loaded from
``data/`` directly, so both paths give an identical result.
"""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from linfilecopy.log import get_logger  # noqa: E402
from linfilecopy.paths import DATA_DIR  # noqa: E402

RESOURCE_PREFIX = "/io/github/mensuramedia/LinFileCopy"
ICON_SUBDIR = "icons/hicolor/scalable/actions"
_log = get_logger(__name__)
_registered = False


def register() -> bool:
    """Make the ``lfc-*`` icons available to GTK. Returns True if the bundle was used."""
    global _registered
    if _registered:
        return True
    theme = Gtk.IconTheme.get_default()
    bundle = DATA_DIR / "linfilecopy.gresource"
    if bundle.is_file() and not _bundle_is_stale(bundle):
        try:
            Gio.resources_register(Gio.Resource.load(str(bundle)))
            theme.add_resource_path(f"{RESOURCE_PREFIX}/{ICON_SUBDIR}")
            _registered = True
            return True
        except GLib.Error as exc:
            _log.warning("could not load %s (%s); using source files", bundle, exc.message)
    theme.append_search_path(str(DATA_DIR / ICON_SUBDIR))
    _registered = True
    return False


def _bundle_is_stale(bundle: Path) -> bool:
    """True when a source checkout has icons or CSS newer than the compiled bundle."""
    built = bundle.stat().st_mtime
    sources = [*DATA_DIR.glob("*.css"), *(DATA_DIR / ICON_SUBDIR).glob("*.svg")]
    return any(p.stat().st_mtime > built for p in sources)


def _resource_exists(path: str) -> bool:
    try:
        Gio.resources_get_info(path, Gio.ResourceLookupFlags.NONE)
        return True
    except GLib.Error:
        return False


APP_ID = "io.github.mensuramedia.LinFileCopy"


def app_icon_path() -> Path:
    return DATA_DIR / "app-icon" / f"{APP_ID}.svg"


def set_default_window_icon() -> None:
    """Use the bundled app icon for every window (installed builds also ship it in hicolor)."""
    theme = Gtk.IconTheme.get_default()
    if theme.has_icon(APP_ID):
        Gtk.Window.set_default_icon_name(APP_ID)
        return
    try:
        Gtk.Window.set_default_icon_from_file(str(app_icon_path()))
    except GLib.Error as exc:
        _log.warning("app icon not loaded: %s", exc.message)


def load_css(name: str) -> Gtk.CssProvider:
    """Load ``data/<name>`` (from the bundle when registered) into a new provider."""
    provider = Gtk.CssProvider()
    resource = f"{RESOURCE_PREFIX}/{name}"
    if _resource_exists(resource):
        provider.load_from_resource(resource)
    else:
        provider.load_from_path(str(DATA_DIR / name))
    return provider


def add_provider(provider: Gtk.CssProvider, priority: int = Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION) -> None:
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(screen, provider, priority)


def remove_provider(provider: Gtk.CssProvider) -> None:
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.remove_provider_for_screen(screen, provider)
