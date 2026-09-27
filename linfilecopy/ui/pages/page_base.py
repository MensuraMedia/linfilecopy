"""Base class for dashboard pages (pattern from gtk-python-dashboard-starter)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from linfilecopy.ui.components.component_common import add_classes, label  # noqa: E402
from linfilecopy.ui.context import AppContext  # noqa: E402


class BasePage(Gtk.ScrolledWindow):
    """A scrollable page. Subclasses implement :meth:`build_content`.

    ``self.content`` is the vertical box to fill. Pages that need their own
    scrolling layout (the designer) pass ``scroll=False`` and fill
    ``self.content`` with their own scrolled areas.
    """

    page_id = "base"
    title = ""

    def __init__(self, ctx: AppContext, scroll: bool = True) -> None:
        super().__init__()
        self.ctx = ctx
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC if scroll else Gtk.PolicyType.NEVER)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        add_classes(self.content, "lfc-page")
        self.add(self.content)
        self.build_content()

    def build_content(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def on_shown(self) -> None:
        """Called each time the page becomes visible."""

    def after_show_all(self) -> None:
        """Called once after the window's first show_all(): re-apply hidden states."""

    def subtitle(self) -> str:
        """Text shown under the window title while this page is visible."""
        return self.title

    def add_title(self, text: str) -> Gtk.Label:
        lbl = label(text, "lfc-page-title")
        self.content.pack_start(lbl, False, False, 0)
        return lbl
