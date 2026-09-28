"""Sidebar: page navigation plus the connected-drives footer."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GObject, Gtk  # noqa: E402

from linfilecopy.i18n import _  # noqa: E402
from linfilecopy.ui.components.component_common import add_classes, label  # noqa: E402
from linfilecopy.ui.icons import SIZE_NAV, icon, icon_name  # noqa: E402

NAV_ITEMS: list[tuple[str, str]] = [
    ("dashboard", _("Dashboard")),
    ("quickview", _("Quick View")),
    ("designer", _("Job Designer")),
    ("transfers", _("Active Transfers")),
    ("history", _("History & Logs")),
    ("scheduler", _("Scheduler")),
    ("settings", _("Settings")),
]
SIDEBAR_WIDTH = 212


class _NavRow(Gtk.ListBoxRow):
    def __init__(self, page_id: str, text: str, index: int) -> None:
        super().__init__()
        self.page_id = page_id
        add_classes(self, "lfc-nav")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.image = icon(f"nav-{page_id}", SIZE_NAV)
        self.text = label(text)
        self.count = label("", "lfc-count")
        self.count.set_no_show_all(True)
        # Live-activity dot, right-aligned: breathes while work is running.
        self.dot = Gtk.Box()
        self.dot.set_valign(Gtk.Align.CENTER)
        add_classes(self.dot, "lfc-live-dot")
        self.dot.set_no_show_all(True)
        box.pack_start(self.image, False, False, 0)
        box.pack_start(self.text, True, True, 0)
        box.pack_end(self.dot, False, False, 0)
        box.pack_end(self.count, False, False, 0)
        self.add(box)
        self.set_tooltip_text(f"{text} (Ctrl+{index})")
        self.get_accessible().set_name(text)

    def set_selected_look(self, selected: bool) -> None:
        suffix = "-active" if selected else ""
        self.image.set_from_icon_name(icon_name(f"nav-{self.page_id}{suffix}"), Gtk.IconSize.BUTTON)
        self.image.set_pixel_size(SIZE_NAV)


class Sidebar(Gtk.Box):
    """Navigation list. Emits ``page-changed(page_id)`` when the user picks a page."""

    __gsignals__ = {"page-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        add_classes(self, "lfc-sidebar")
        self.set_size_request(SIDEBAR_WIDTH, -1)
        self._rows: dict[str, _NavRow] = {}
        self._compact = False

        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.get_accessible().set_name(_("Pages"))
        for i, (page_id, text) in enumerate(NAV_ITEMS, start=1):
            r = _NavRow(page_id, text, i)
            self._rows[page_id] = r
            self.list.add(r)
        self.list.connect("row-selected", self._on_row_selected)
        self.list.set_margin_top(8)
        self.pack_start(self.list, False, False, 0)

        self.pack_start(Gtk.Box(), True, True, 0)  # spacer pushes drives to the bottom

        self.drives_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        add_classes(self.drives_box, "lfc-drives")
        self.drives_heading = label(_("DRIVES"), "lfc-sidebar-heading")
        self.drives_box.pack_start(self.drives_heading, False, False, 0)
        self.drives_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.drives_list.set_margin_bottom(18)   # lift the drive list clear of the window edge
        self.drives_box.pack_start(self.drives_list, False, False, 0)
        self.pack_end(self.drives_box, False, False, 0)

    def select(self, page_id: str) -> None:
        r = self._rows.get(page_id)
        if r is not None and self.list.get_selected_row() is not r:
            self.list.select_row(r)

    def set_count(self, page_id: str, count: int) -> None:
        r = self._rows[page_id]
        r.count.set_text(str(count))
        r.count.set_visible(count > 0 and not self._compact)

    def set_activity(self, page_id: str, state: str) -> None:
        """Right-aligned dot on a nav row: "running" breathes, "idle" is a steady
        dimmed dot (paused or waiting work), "none" hides it."""
        r = self._rows[page_id]
        ctx = r.dot.get_style_context()
        ctx.remove_class("running")
        ctx.remove_class("idle")
        if state in ("running", "idle"):
            ctx.add_class(state)
            r.dot.show()
            names = {"running": _("a transfer is running"), "idle": _("transfers are paused or waiting")}
            r.dot.set_tooltip_text(names[state])
            r.get_accessible().set_description(names[state])
        else:
            r.dot.hide()
            r.get_accessible().set_description("")

    def set_compact(self, compact: bool) -> None:
        """Icons only (medium widths)."""
        if compact == self._compact:
            return
        self._compact = compact
        self.set_size_request(56 if compact else SIDEBAR_WIDTH, -1)
        for r in self._rows.values():
            r.text.set_visible(not compact)
            r.count.set_visible(not compact and bool(r.count.get_text()) and r.count.get_text() != "0")
        self.drives_box.set_visible(not compact)

    def _on_row_selected(self, _lb: Gtk.ListBox, row: _NavRow | None) -> None:
        for r in self._rows.values():
            r.set_selected_look(r is row)
        if row is not None:
            self.emit("page-changed", row.page_id)
