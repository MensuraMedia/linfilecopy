"""Small reusable widgets shared by every page.

These mirror the Adwaita patterns used in the mockups (boxed lists, preference
rows, badges, message bars, stat tiles) with plain GTK 3 widgets and the
``lfc-*`` CSS classes from ``data/style.css``.
"""
from __future__ import annotations

from typing import Callable, Iterable, Sequence

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from linfilecopy.formatting import format_bytes, format_duration  # noqa: E402,F401
from linfilecopy.ui.icons import SIZE_TILE, icon  # noqa: E402


def add_classes(widget: Gtk.Widget, *classes: str) -> Gtk.Widget:
    ctx = widget.get_style_context()
    for c in classes:
        if c:
            ctx.add_class(c)
    return widget


def label(
    text: str = "",
    *classes: str,
    xalign: float = 0.0,
    wrap: bool = False,
    markup: bool = False,
    selectable: bool = False,
    ellipsize: bool = False,
) -> Gtk.Label:
    lbl = Gtk.Label()
    if markup:
        lbl.set_markup(text)
    else:
        lbl.set_text(text)
    lbl.set_xalign(xalign)
    if wrap:
        lbl.set_line_wrap(True)
        lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        lbl.set_max_width_chars(60)
    if ellipsize:
        lbl.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
    lbl.set_selectable(selectable)
    return add_classes(lbl, *classes)  # type: ignore[return-value]


def esc(text: str) -> str:
    """Escape untrusted text (file names) for Pango markup."""
    return GLib.markup_escape_text(text, -1)


def hbox(spacing: int = 8, *children: Gtk.Widget) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
    for c in children:
        box.pack_start(c, False, False, 0)
    return box


def vbox(spacing: int = 8, *children: Gtk.Widget) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    for c in children:
        box.pack_start(c, False, False, 0)
    return box


def boxed_list() -> Gtk.ListBox:
    """An Adwaita-style boxed list of rows."""
    lb = Gtk.ListBox()
    lb.set_selection_mode(Gtk.SelectionMode.NONE)
    add_classes(lb, "lfc-boxed-list")
    return lb


def row(
    title: str,
    subtitle: str | None = None,
    icon_id: str | None = None,
    suffix: Iterable[Gtk.Widget] = (),
    sub: bool = False,
    tooltip: str | None = None,
    activatable_widget: Gtk.Widget | None = None,
) -> Gtk.ListBoxRow:
    """A preference row: optional icon, title + subtitle, then suffix widgets.

    ``activatable_widget`` is focused/toggled when the row is activated and
    receives the title as its accessible name.
    """
    r = Gtk.ListBoxRow()
    r.set_activatable(activatable_widget is not None)
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    if icon_id:
        img = icon(icon_id)
        add_classes(img, "lfc-dim")
        box.pack_start(img, False, False, 0)
    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
    text.set_valign(Gtk.Align.CENTER)
    t = label(title, wrap=True)
    text.pack_start(t, False, False, 0)
    r.subtitle_label = None  # type: ignore[attr-defined]
    if subtitle is not None:
        s = label(subtitle, "lfc-dim", "lfc-small", wrap=True)
        text.pack_start(s, False, False, 0)
        r.subtitle_label = s  # type: ignore[attr-defined]
    box.pack_start(text, True, True, 0)
    for w in suffix:
        w.set_valign(Gtk.Align.CENTER)
        box.pack_start(w, False, False, 0)
    r.add(box)
    r.title_label = t  # type: ignore[attr-defined]
    if sub:
        add_classes(r, "lfc-subrow")
    if tooltip:
        r.set_tooltip_text(tooltip)
    if activatable_widget is not None:
        activatable_widget.get_accessible().set_name(title)
        r.activate_target = activatable_widget  # type: ignore[attr-defined]
    return r


def activate_rows(listbox: Gtk.ListBox) -> None:
    """Make activating a row toggle its switch/check or focus its control."""

    def on_activated(_lb: Gtk.ListBox, r: Gtk.ListBoxRow) -> None:
        target = getattr(r, "activate_target", None)
        if isinstance(target, Gtk.Switch):
            if target.get_sensitive():
                target.set_active(not target.get_active())
        elif isinstance(target, Gtk.ToggleButton):
            target.set_active(not target.get_active())
        elif target is not None:
            target.grab_focus()

    listbox.connect("row-activated", on_activated)


def switch(active: bool = False, on_change: Callable[[bool], None] | None = None) -> Gtk.Switch:
    sw = Gtk.Switch()
    sw.set_active(active)
    sw.set_valign(Gtk.Align.CENTER)
    if on_change:
        sw.connect("notify::active", lambda s, _p: on_change(s.get_active()))
    return sw


def switch_row(
    title: str,
    subtitle: str | None,
    icon_id: str | None,
    active: bool,
    on_change: Callable[[bool], None] | None = None,
    sub: bool = False,
    tooltip: str | None = None,
) -> tuple[Gtk.ListBoxRow, Gtk.Switch]:
    sw = switch(active, on_change)
    return row(title, subtitle, icon_id, [sw], sub=sub, tooltip=tooltip, activatable_widget=sw), sw


def group(title: str, icon_id: str | None = None, note: str | None = None, *children: Gtk.Widget) -> Gtk.Box:
    """A titled section: heading line followed by children."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    if icon_id:
        head.pack_start(add_classes(icon(icon_id), "lfc-dim"), False, False, 0)
    head.pack_start(label(title, "lfc-group-title"), False, False, 0)
    if note:
        n = label(note, "lfc-dim", "lfc-small")
        head.pack_end(n, False, False, 0)
        box.note_label = n  # type: ignore[attr-defined]
    box.pack_start(head, False, False, 0)
    for c in children:
        box.pack_start(c, False, False, 0)
    return box


def badge(text: str, kind: str = "", icon_id: str | None = None) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
    if icon_id:
        box.pack_start(icon(icon_id), False, False, 0)
    lbl = label(text)
    box.pack_start(lbl, False, False, 0)
    box.badge_label = lbl  # type: ignore[attr-defined]
    box.set_valign(Gtk.Align.CENTER)
    add_classes(box, "lfc-badge", kind)
    return box


def set_badge(box: Gtk.Box, text: str, kind: str) -> None:
    ctx = box.get_style_context()
    for k in ("ok", "warn", "err", "info"):
        ctx.remove_class(k)
    if kind:
        ctx.add_class(kind)
    box.badge_label.set_text(text)  # type: ignore[attr-defined]


def status_icon(icon_id: str, kind: str = "") -> Gtk.Image:
    img = icon(icon_id)
    return add_classes(img, f"lfc-{kind}" if kind else "")  # type: ignore[return-value]


class MessageBar(Gtk.Box):
    """Inline message with icon, bold title, body and optional action buttons."""

    def __init__(self, kind: str = "", icon_id: str = "misc-info") -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        add_classes(self, "lfc-message")
        self._kind = ""
        self._icon = icon(icon_id)
        self._icon.set_valign(Gtk.Align.START)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.title = label("", wrap=True)
        self.body = label("", "lfc-small", wrap=True)
        text.pack_start(self.title, False, False, 0)
        text.pack_start(self.body, False, False, 0)
        self.actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.actions.set_valign(Gtk.Align.CENTER)
        self.pack_start(self._icon, False, False, 0)
        self.pack_start(text, True, True, 0)
        self.pack_start(self.actions, False, False, 0)
        self.set_kind(kind, icon_id)
        self.set_no_show_all(True)

    def set_kind(self, kind: str, icon_id: str | None = None) -> None:
        ctx = self.get_style_context()
        if self._kind:
            ctx.remove_class(self._kind)
        if kind:
            ctx.add_class(kind)
        self._kind = kind
        if icon_id:
            self._icon.set_from_icon_name(f"lfc-{icon_id}-symbolic", Gtk.IconSize.BUTTON)

    def show_message(self, title: str, body: str = "", kind: str | None = None, icon_id: str | None = None) -> None:
        if kind is not None:
            self.set_kind(kind, icon_id)
        self.title.set_markup(f"<b>{esc(title)}</b>" if title else "")
        self.title.set_visible(bool(title))
        self.body.set_text(body)
        self.body.set_visible(bool(body))
        self.set_no_show_all(False)
        self.show_all()
        self.title.set_visible(bool(title))
        self.body.set_visible(bool(body))

    def hide_message(self) -> None:
        self.hide()
        self.set_no_show_all(True)


def stat_tile(icon_id: str, value: str, caption: str, bad: bool = False) -> tuple[Gtk.Box, Gtk.Label, Gtk.Label]:
    tile = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    add_classes(tile, "lfc-tile", "bad" if bad else "")
    img = icon(icon_id, SIZE_TILE)
    img.set_valign(Gtk.Align.START)
    tile.pack_start(img, False, False, 0)
    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    num = label(value, "lfc-stat-num")
    cap = label(caption, "lfc-dim", "lfc-small", wrap=True)
    text.pack_start(num, False, False, 0)
    text.pack_start(cap, False, False, 0)
    tile.pack_start(text, True, True, 0)
    return tile, num, cap


class Segmented(Gtk.Box):
    """A linked row of mutually exclusive toggle buttons (radio-like, accessible)."""

    def __init__(
        self,
        options: Sequence[tuple[str, str, str | None]],
        active: str,
        on_change: Callable[[str], None] | None = None,
        tooltips: dict[str, str] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        add_classes(self, "linked")
        self.set_halign(Gtk.Align.START)
        self.buttons: dict[str, Gtk.ToggleButton] = {}
        self._value = active
        self._on_change = on_change
        self._updating = False
        for key, text, icon_id in options:
            btn = Gtk.ToggleButton()
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            if icon_id:
                inner.pack_start(icon(icon_id), False, False, 0)
            inner.pack_start(Gtk.Label(label=text), False, False, 0)
            btn.add(inner)
            add_classes(btn, "lfc-segment")
            btn.get_accessible().set_name(text)
            if tooltips and key in tooltips:
                btn.set_tooltip_text(tooltips[key])
            btn.connect("toggled", self._on_toggled, key)
            self.buttons[key] = btn
            self.pack_start(btn, False, False, 0)
        self.set_value(active, notify=False)

    @property
    def value(self) -> str:
        return self._value

    def set_value(self, key: str, notify: bool = True) -> None:
        self._updating = True
        for k, b in self.buttons.items():
            b.set_active(k == key)
        self._updating = False
        changed = key != self._value
        self._value = key
        if notify and changed and self._on_change:
            self._on_change(key)

    def set_option_sensitive(self, key: str, sensitive: bool, tooltip: str | None = None) -> None:
        btn = self.buttons[key]
        btn.set_sensitive(sensitive)
        if tooltip is not None:
            btn.set_tooltip_text(tooltip)

    def _on_toggled(self, btn: Gtk.ToggleButton, key: str) -> None:
        if self._updating:
            return
        if not btn.get_active():
            # Keep one option selected: re-activate the clicked one.
            if key == self._value:
                self._updating = True
                btn.set_active(True)
                self._updating = False
            return
        self.set_value(key)


def combo(options: Sequence[tuple[str, str]], active: str, on_change: Callable[[str], None] | None = None) -> Gtk.ComboBoxText:
    cb = Gtk.ComboBoxText()
    for key, text in options:
        cb.append(key, text)
    cb.set_active_id(active)
    cb.set_valign(Gtk.Align.CENTER)
    if on_change:
        cb.connect("changed", lambda c: on_change(c.get_active_id() or ""))
    return cb


def spin(value: float, lower: float, upper: float, step: float = 1, digits: int = 0,
         on_change: Callable[[float], None] | None = None, width_chars: int = 5) -> Gtk.SpinButton:
    adj = Gtk.Adjustment(value=value, lower=lower, upper=upper, step_increment=step, page_increment=step * 10)
    sb = Gtk.SpinButton(adjustment=adj, digits=digits)
    sb.set_width_chars(width_chars)
    sb.set_valign(Gtk.Align.CENTER)
    if on_change:
        sb.connect("value-changed", lambda s: on_change(s.get_value()))
    return sb


def clear(container: Gtk.Container) -> None:
    for child in container.get_children():
        container.remove(child)
        child.destroy()
