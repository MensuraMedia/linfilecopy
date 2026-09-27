"""Designer side panels: command preview, validation issues, collapsible sections."""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from linfilecopy.i18n import _, ngettext  # noqa: E402
from linfilecopy.model.validation import ERROR, WARNING, Issue  # noqa: E402
from linfilecopy.ui.components.component_common import add_classes, badge, clear, esc, label, set_badge  # noqa: E402
from linfilecopy.ui.icons import button, icon, icon_name  # noqa: E402


class CommandPreviewWidget(Gtk.Box):
    """The live command / plan preview with a copy button."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        add_classes(self, "lfc-card")
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        head.pack_start(icon("misc-command"), False, False, 0)
        self.title = label(_("Command"), "lfc-group-title")
        head.pack_start(self.title, False, False, 0)
        self.engine_badge = badge("rsync", "info")
        head.pack_end(self.engine_badge, False, False, 0)
        self.pack_start(head, False, False, 0)

        self.view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True)
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(10)
        self.view.set_right_margin(10)
        self.view.set_top_margin(8)
        self.view.set_bottom_margin(8)
        add_classes(self.view, "lfc-cmd")
        self.view.get_accessible().set_name(_("Command that will run"))
        frame = Gtk.Frame()
        add_classes(frame, "lfc-cmd-frame")
        frame.add(self.view)
        self.pack_start(frame, False, False, 0)
        buf = self.view.get_buffer()
        self._comment = buf.create_tag("comment", foreground_rgba=None)
        self._comment.props.style = Pango.Style.ITALIC
        self._flag = buf.create_tag("flag", weight=Pango.Weight.NORMAL)

        self.copy_button = button("action-copy-command", _("Copy command"), _("Copy the command to the clipboard (Ctrl+Shift+C)"))
        self.copy_button.set_halign(Gtk.Align.START)
        self.copy_button.connect("clicked", lambda _b: self.copy_to_clipboard())
        self.pack_start(self.copy_button, False, False, 0)
        self._text = ""

    def set_plan(self, text: str, steps: int, engine: str) -> None:
        self._text = text
        self.title.set_text(_("Command") if steps <= 1 else _("Plan · {n} steps").format(n=steps))
        set_badge(self.engine_badge, engine, "info")
        buf = self.view.get_buffer()
        buf.set_text("")
        it = buf.get_end_iter()
        for i, line in enumerate(text.splitlines()):
            if i:
                buf.insert(it, "\n")
            if line.startswith("#"):
                buf.insert_with_tags(it, line, self._comment)
            else:
                buf.insert(it, line)
        dim = self.get_style_context().lookup_color("lfc_dim")
        if dim[0]:
            self._comment.props.foreground_rgba = dim[1]

    def copy_to_clipboard(self) -> None:
        if self._text:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self._text, -1)
            self.copy_button.get_child().get_children()[-1].set_text(_("Copied"))
            GLib.timeout_add(1500, self._reset_copy_label)

    def _reset_copy_label(self) -> bool:
        self.copy_button.get_child().get_children()[-1].set_text(_("Copy command"))
        return GLib.SOURCE_REMOVE


class IssuesWidget(Gtk.Box):
    """Validation result: "Ready to run", or errors / warnings / notes with fixes."""

    LEVEL_ICON = {ERROR: ("status-failed", "err"), WARNING: ("status-warning", "warn"), "info": ("misc-info", "accent")}

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        add_classes(self, "lfc-card")
        self.head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.head_icon = icon("status-success")
        self.head_label = label(_("Checking…"), "lfc-group-title")
        self.head.pack_start(self.head_icon, False, False, 0)
        self.head.pack_start(self.head_label, False, False, 0)
        self.pack_start(self.head, False, False, 0)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.pack_start(self.body, False, False, 0)
        self.extra = label("", "lfc-dim", "lfc-small", wrap=True)
        self.pack_start(self.extra, False, False, 0)

    def set_issues(self, issues: list[Issue], extra: str = "") -> None:
        clear(self.body)
        errors = [i for i in issues if i.level == ERROR]
        warnings = [i for i in issues if i.level == WARNING]
        ctx = self.head_icon.get_style_context()
        for c in ("lfc-ok", "lfc-err", "lfc-warn"):
            ctx.remove_class(c)
        if errors:
            self.head_icon.set_from_icon_name(icon_name("status-failed"), Gtk.IconSize.BUTTON)
            ctx.add_class("lfc-err")
            self.head_label.set_text(ngettext("{n} problem to fix", "{n} problems to fix", len(errors)).format(n=len(errors)))
        elif warnings:
            self.head_icon.set_from_icon_name(icon_name("status-warning"), Gtk.IconSize.BUTTON)
            ctx.add_class("lfc-warn")
            self.head_label.set_text(ngettext("Ready · {n} warning", "Ready · {n} warnings", len(warnings)).format(n=len(warnings)))
        else:
            self.head_icon.set_from_icon_name(icon_name("status-success"), Gtk.IconSize.BUTTON)
            ctx.add_class("lfc-ok")
            self.head_label.set_text(_("Ready to run"))
        for issue in [*errors, *warnings]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            icon_id, cls = self.LEVEL_ICON[issue.level]
            img = icon(icon_id)
            img.set_valign(Gtk.Align.START)
            add_classes(img, f"lfc-{cls}")
            row.pack_start(img, False, False, 0)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text.pack_start(label(issue.message, wrap=True), False, False, 0)
            if issue.fix:
                text.pack_start(label(issue.fix, "lfc-dim", "lfc-small", wrap=True), False, False, 0)
            row.pack_start(text, True, True, 0)
            self.body.pack_start(row, False, False, 0)
        self.body.show_all()
        self.extra.set_text(extra)
        self.extra.set_visible(bool(extra))


class Section(Gtk.Box):
    """A collapsible group for the Advanced view: header with icon, title, note and summary."""

    def __init__(self, icon_id: str, title: str, note: str = "", expanded: bool = False,
                 on_toggle: Callable[[bool], None] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._on_toggle = on_toggle
        self.header = Gtk.Button()
        self.header.set_relief(Gtk.ReliefStyle.NONE)
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.caret = icon("action-collapse" if expanded else "action-expand")
        hb.pack_start(self.caret, False, False, 0)
        hb.pack_start(add_classes(icon(icon_id), "lfc-dim"), False, False, 0)
        self.title_label = label(title, "lfc-group-title")
        hb.pack_start(self.title_label, False, False, 0)
        self.summary = label("", "lfc-dim", "lfc-small", ellipsize=True)
        hb.pack_start(self.summary, True, True, 6)
        if note:
            hb.pack_end(label(note, "lfc-dim", "lfc-small"), False, False, 0)
        self.header.add(hb)
        self.header.connect("clicked", lambda _b: self.set_expanded(not self.expanded))
        self.header.get_accessible().set_name(title)
        self.pack_start(self.header, False, False, 0)
        self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=150)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.revealer.add(self.body)
        self.revealer.set_reveal_child(expanded)
        self.pack_start(self.revealer, False, False, 0)
        self.expanded = expanded
        self.summary.set_visible(not expanded)

    def set_expanded(self, expanded: bool) -> None:
        self.expanded = expanded
        self.revealer.set_reveal_child(expanded)
        self.caret.set_from_icon_name(icon_name("action-collapse" if expanded else "action-expand"), Gtk.IconSize.BUTTON)
        self.summary.set_visible(not expanded)
        if self._on_toggle:
            self._on_toggle(expanded)

    def set_summary(self, text: str) -> None:
        self.summary.set_markup(f"<small>{esc(text)}</small>" if text else "")
