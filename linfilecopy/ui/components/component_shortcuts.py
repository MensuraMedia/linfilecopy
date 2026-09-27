"""Keyboard shortcuts window (Ctrl+?)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from linfilecopy.i18n import _  # noqa: E402

SHORTCUT_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    (_("Jobs"), [
        ("<Control>n", _("New job")),
        ("<Control>s", _("Save job")),
        ("<Control>Return", _("Start")),
        ("<Control><Shift>p", _("Preview (dry run)")),
        ("<Control><Shift>c", _("Copy command")),
    ]),
    (_("Transfers"), [
        ("space", _("Pause or resume the selected transfer")),
        ("Escape", _("Cancel the selected transfer (asks first)")),
        ("<Control>e", _("Eject the destination drive")),
    ]),
    (_("Navigation"), [
        ("<Control>1", _("Dashboard")),
        ("<Control>2", _("Job Designer")),
        ("<Control>3", _("Active Transfers")),
        ("<Control>4", _("History & Logs")),
        ("<Control>5", _("Scheduler")),
        ("<Control>6", _("Settings")),
        ("<Control>question", _("Keyboard shortcuts")),
        ("<Control>q", _("Quit")),
    ]),
]


def build_shortcuts_window() -> Gtk.ShortcutsWindow:
    win = Gtk.ShortcutsWindow(modal=True)
    section = Gtk.ShortcutsSection(visible=True, section_name="main", max_height=12)
    for title, items in SHORTCUT_GROUPS:
        grp = Gtk.ShortcutsGroup(visible=True, title=title)
        for accel, text in items:
            grp.add(Gtk.ShortcutsShortcut(visible=True, accelerator=accel, title=text))
        section.add(grp)
    win.add(section)
    return win
