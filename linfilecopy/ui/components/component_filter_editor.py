"""Ordered include/exclude rule editor (#5)."""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from linfilecopy.i18n import _  # noqa: E402
from linfilecopy.model.enums import FilterAction  # noqa: E402
from linfilecopy.model.job import FilterRule  # noqa: E402
from linfilecopy.ui.components.component_common import add_classes, boxed_list, clear, label  # noqa: E402
from linfilecopy.ui.icons import button  # noqa: E402


class FilterEditorWidget(Gtk.Box):
    """Edits a list of FilterRule in place and calls ``on_change`` after every edit."""

    def __init__(self, on_change: Callable[[], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.on_change = on_change
        self.rules: list[FilterRule] = []
        self.listbox = boxed_list()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.get_accessible().set_name(_("Filter rules"))
        self.pack_start(self.listbox, False, False, 0)
        self.empty = label(_("No custom rules. Everything is copied except the presets you picked."), "lfc-dim", "lfc-small", wrap=True)
        self.pack_start(self.empty, False, False, 0)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        linked = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        add_classes(linked, "linked")
        add = button("action-new", None, _("Add a rule"))
        add.connect("clicked", lambda _b: self._add())
        remove = button("action-remove", None, _("Remove the selected rule"))
        remove.connect("clicked", lambda _b: self._remove())
        up = button("action-move-up", None, _("Move the selected rule up"))
        up.connect("clicked", lambda _b: self._move(-1))
        down = button("action-move-down", None, _("Move the selected rule down"))
        down.connect("clicked", lambda _b: self._move(1))
        for b in (add, remove, up, down):
            linked.pack_start(b, False, False, 0)
        bar.pack_start(linked, False, False, 0)
        self.bar = bar
        self.pack_start(bar, False, False, 0)

    def set_rules(self, rules: list[FilterRule]) -> None:
        self.rules = rules
        self._rebuild()

    def _rebuild(self, select: int | None = None) -> None:
        clear(self.listbox)
        for i, rule in enumerate(self.rules):
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            action = Gtk.ComboBoxText()
            action.append(FilterAction.EXCLUDE.value, _("Exclude"))
            action.append(FilterAction.INCLUDE.value, _("Include"))
            action.set_active_id(rule.action.value)
            action.get_accessible().set_name(_("Rule {n} action").format(n=i + 1))
            action.connect("changed", self._on_action, i)
            entry = Gtk.Entry(text=rule.pattern)
            entry.set_placeholder_text(_("Pattern, e.g. *.iso or Downloads/"))
            entry.get_style_context().add_class("lfc-mono")
            entry.get_accessible().set_name(_("Rule {n} pattern").format(n=i + 1))
            entry.set_tooltip_text(_("* matches within a name, ** across folders, a trailing / matches folders only, a leading / anchors at the source folder."))
            entry.connect("changed", self._on_pattern, i)
            box.pack_start(action, False, False, 0)
            box.pack_start(entry, True, True, 0)
            row.add(box)
            self.listbox.add(row)
        self.listbox.show_all()
        self.empty.set_visible(not self.rules)
        self.listbox.set_visible(bool(self.rules))
        if select is not None and 0 <= select < len(self.rules):
            self.listbox.select_row(self.listbox.get_row_at_index(select))

    def _selected(self) -> int | None:
        row = self.listbox.get_selected_row()
        return row.get_index() if row is not None else None

    def _add(self) -> None:
        self.rules.append(FilterRule(FilterAction.EXCLUDE, ""))
        self._rebuild(len(self.rules) - 1)
        last = self.listbox.get_row_at_index(len(self.rules) - 1)
        if last is not None:
            last.get_child().get_children()[1].grab_focus()
        self.on_change()

    def _remove(self) -> None:
        i = self._selected()
        if i is None and self.rules:
            i = len(self.rules) - 1
        if i is not None:
            del self.rules[i]
            self._rebuild(min(i, len(self.rules) - 1))
            self.on_change()

    def _move(self, delta: int) -> None:
        i = self._selected()
        if i is None:
            return
        j = i + delta
        if 0 <= j < len(self.rules):
            self.rules[i], self.rules[j] = self.rules[j], self.rules[i]
            self._rebuild(j)
            self.on_change()

    def _on_action(self, combo: Gtk.ComboBoxText, i: int) -> None:
        self.rules[i].action = FilterAction(combo.get_active_id() or "exclude")
        self.on_change()

    def _on_pattern(self, entry: Gtk.Entry, i: int) -> None:
        self.rules[i].pattern = entry.get_text()
        self.on_change()
