"""Dialogs: preview results (B7/#4, #13), delete confirmation (B2), generic confirm."""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from linfilecopy.engine.progress import Change, ChangeKind  # noqa: E402
from linfilecopy.engine.runner import JobRun  # noqa: E402
from linfilecopy.engine.twoway import A_TO_B  # noqa: E402
from linfilecopy.formatting import format_bytes  # noqa: E402
from linfilecopy.i18n import _, ngettext  # noqa: E402
from linfilecopy.model.enums import Mode, RunStatus  # noqa: E402
from linfilecopy.ui.components.component_common import MessageBar, Segmented, add_classes, badge, esc, label  # noqa: E402
from linfilecopy.ui.icons import SIZE_EMPTY, button, icon, icon_name  # noqa: E402

KIND_ICON = {
    ChangeKind.NEW: ("delta-create", "lfc-ok"),
    ChangeKind.UPDATE: ("delta-update", "lfc-accent"),
    ChangeKind.DELETE: ("delta-delete", "lfc-err"),
    ChangeKind.ATTRS: ("feat-metadata", "lfc-dim"),
    ChangeKind.LINK: ("feat-linkdest", "lfc-dim"),
    ChangeKind.CONFLICT: ("policy-conflict", "lfc-warn"),
}
MAX_ROWS = 5000


def change_counts(changes: list[Change]) -> dict[ChangeKind, int]:
    counts: dict[ChangeKind, int] = {}
    for c in changes:
        if c.kind is ChangeKind.NEW and c.is_dir:
            continue
        counts[c.kind] = counts.get(c.kind, 0) + 1
    return counts


def deletions(changes: list[Change]) -> list[Change]:
    return [c for c in changes if c.kind is ChangeKind.DELETE]


class PreviewDialog(Gtk.Dialog):
    """Shows a preview run live, then its list of planned changes.

    ``on_run_for_real`` is called when the user presses "Run for real".
    """

    def __init__(self, parent: Gtk.Window, run: JobRun, on_run_for_real: Callable[[], None] | None,
                 dest_label: str = "") -> None:
        super().__init__(title=_("Preview: {job}").format(job=run.job.name), transient_for=parent, modal=True,
                         use_header_bar=True)
        self.run_obj = run
        self.on_run_for_real = on_run_for_real
        self.dest_label = dest_label
        self.set_default_size(760, 560)
        hb = self.get_header_bar()
        copy_btn = button("action-copy-command", _("Copy list"), _("Copy the list of changes"))
        copy_btn.connect("clicked", self._copy)
        hb.pack_start(copy_btn)
        self.run_button = button("action-start", _("Run for real") if run.job.mode is not Mode.TWO_WAY else _("Sync now"),
                                 None, "suggested-action")
        self.run_button.set_sensitive(False)
        self.run_button.connect("clicked", self._on_run_clicked)
        if on_run_for_real is not None:
            hb.pack_end(self.run_button)

        area = self.get_content_area()
        area.set_spacing(12)
        for side in ("top", "bottom", "start", "end"):
            getattr(area, f"set_margin_{side}")(16)

        self.status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.spinner = Gtk.Spinner(active=True)
        self.status.pack_start(self.spinner, False, False, 0)
        self.status_label = label(_("Comparing source and destination…"))
        self.status.pack_start(self.status_label, False, False, 0)
        area.pack_start(self.status, False, False, 0)

        self.badges = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6, column_spacing=6)
        area.pack_start(self.badges, False, False, 0)
        self.message = MessageBar("err", "status-failed")
        area.pack_start(self.message, False, False, 0)

        tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.filter = Segmented([("all", _("All"), None), ("new", _("New"), None), ("update", _("Updated"), None),
                                 ("delete", _("Deleted"), None), ("conflict", _("Conflicts"), None)],
                                "all", lambda _v: self._refilter())
        tools.pack_start(self.filter, False, False, 0)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text(_("Filter paths"))
        self.search.connect("search-changed", lambda _e: self._refilter())
        tools.pack_start(self.search, True, True, 0)
        area.pack_start(tools, False, False, 0)

        # icon name, path, detail, kind
        self.store = Gtk.ListStore(str, str, str, str)
        self.filtered = self.store.filter_new()
        self.filtered.set_visible_func(self._visible)
        self.tree = Gtk.TreeView(model=self.filtered, headers_visible=False, enable_search=False)
        self.tree.get_accessible().set_name(_("Planned changes"))
        col = Gtk.TreeViewColumn()
        pix = Gtk.CellRendererPixbuf()
        col.pack_start(pix, False)
        col.add_attribute(pix, "icon-name", 0)
        text = Gtk.CellRendererText(ellipsize=2)
        col.pack_start(text, True)
        col.add_attribute(text, "text", 1)
        col.set_expand(True)
        self.tree.append_column(col)
        detail = Gtk.CellRendererText(xalign=1.0)
        dcol = Gtk.TreeViewColumn("", detail, text=2)
        self.tree.append_column(dcol)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.add(self.tree)
        frame = Gtk.Frame()
        frame.add(scroll)
        area.pack_start(frame, True, True, 0)
        self.empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.empty.set_no_show_all(True)
        area.pack_start(self.empty, False, False, 0)
        self.show_all()
        self.message.hide_message()
        self._timer = GLib.timeout_add(300, self._poll)
        self.connect("destroy", self._on_destroy)

    # ----- live run --------------------------------------------------------------
    def _poll(self) -> bool:
        run = self.run_obj
        if run.active:
            n = len(run.changes)
            self.status_label.set_text(ngettext("Comparing… {n} change found", "Comparing… {n} changes found", n).format(n=n)
                                       if n else run.step_description or _("Comparing source and destination…"))
            return GLib.SOURCE_CONTINUE
        self._timer = 0
        self._show_result()
        return GLib.SOURCE_REMOVE

    def _show_result(self) -> None:
        run = self.run_obj
        self.spinner.stop()
        self.spinner.hide()
        changes = run.changes
        if run.status is RunStatus.FAILED:
            self.status_label.set_text(_("The preview could not be completed."))
            self.message.show_message(run.message, run.fix, "err", "status-failed")
            return
        if run.status is RunStatus.CANCELLED:
            self.status_label.set_text(_("Preview cancelled."))
            return
        counts = change_counts(changes)
        total_bytes = sum(c.size for c in changes if c.kind in (ChangeKind.NEW, ChangeKind.UPDATE))
        if not counts:
            self.status_label.set_text(_("Nothing to do: both sides already match."))
        else:
            self.status_label.set_text(_("This is what will happen. Nothing has been changed yet."))
        for kind, text, cls in (
            (ChangeKind.NEW, ngettext("{n} new", "{n} new", counts.get(ChangeKind.NEW, 0)), "ok"),
            (ChangeKind.UPDATE, ngettext("{n} updated", "{n} updated", counts.get(ChangeKind.UPDATE, 0)), "info"),
            (ChangeKind.DELETE, ngettext("{n} deleted", "{n} deleted", counts.get(ChangeKind.DELETE, 0)), "err"),
            (ChangeKind.CONFLICT, ngettext("{n} conflict", "{n} conflicts", counts.get(ChangeKind.CONFLICT, 0)), "warn"),
            (ChangeKind.ATTRS, ngettext("{n} details only", "{n} details only", counts.get(ChangeKind.ATTRS, 0)), ""),
        ):
            if counts.get(kind):
                self.badges.add(badge(text.format(n=counts[kind]), cls, KIND_ICON[kind][0]))
        if total_bytes:
            self.badges.add(badge(_("{size} to copy").format(size=format_bytes(total_bytes))))
        self.badges.show_all()
        for c in changes[:MAX_ROWS]:
            self.store.append([icon_name(KIND_ICON[c.kind][0]), c.path + ("/" if c.is_dir else ""),
                               self._detail(c), c.kind.value])
        if len(changes) > MAX_ROWS:
            self.store.append([icon_name("misc-info"), _("… and {n} more").format(n=len(changes) - MAX_ROWS), "", "all"])
        self.run_button.set_sensitive(self.on_run_for_real is not None and not
                                      (counts.get(ChangeKind.CONFLICT) and any(c.note == _("changed on both sides") for c in changes)))

    def _detail(self, c: Change) -> str:
        if c.direction:
            arrow = _("to destination") if c.direction == A_TO_B else _("to source")
            if c.kind is ChangeKind.CONFLICT:
                return c.note
            if c.kind is ChangeKind.DELETE:
                return _("moved to .lfc-trash") if self.run_obj.job.twoway.use_trash else _("deleted")
            return f"{arrow} · {format_bytes(c.size)}" if c.size else arrow
        if c.kind is ChangeKind.DELETE:
            return _("will be deleted")
        if c.kind is ChangeKind.ATTRS:
            return _("dates or permissions")
        if c.link_target:
            return f"→ {c.link_target}"
        return format_bytes(c.size) if c.size and not c.is_dir else ""

    def _visible(self, model: Gtk.TreeModel, it: Gtk.TreeIter, _data: object) -> bool:
        kind = model[it][3]
        want = self.filter.value
        if want != "all" and kind != want and kind != "all":
            return False
        q = self.search.get_text().strip().lower()
        return not q or q in model[it][1].lower()

    def _refilter(self) -> None:
        self.filtered.refilter()

    def _copy(self, _b: Gtk.Button) -> None:
        lines = [f"{c.kind.value}\t{c.path}" for c in self.run_obj.changes]
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text("\n".join(lines), -1)

    def _on_run_clicked(self, _b: Gtk.Button) -> None:
        cb = self.on_run_for_real
        self.destroy()
        if cb:
            cb()

    def _on_destroy(self, _w: Gtk.Widget) -> None:
        if getattr(self, "_timer", 0):
            GLib.source_remove(self._timer)
            self._timer = 0
        if self.run_obj.active:
            self.run_obj.cancel()


def confirm_delete(parent: Gtk.Window, dels: list[Change], job_name: str, dest_label: str, source_label: str) -> bool:
    """Ask before a Mirror run deletes files. Returns True to go ahead."""
    n = len(dels)
    dlg = Gtk.Dialog(transient_for=parent, modal=True)
    dlg.set_title(_("Confirm deletion"))
    dlg.set_default_size(480, -1)
    area = dlg.get_content_area()
    area.set_spacing(12)
    for side in ("top", "bottom", "start", "end"):
        getattr(area, f"set_margin_{side}")(20)
    img = icon("status-missing-tool", 48)
    add_classes(img, "lfc-warn")
    area.pack_start(img, False, False, 0)
    title = label(ngettext("Delete {n} file from {dest}?", "Delete {n} files from {dest}?", n).format(n=n, dest=dest_label),
                  "lfc-page-title", xalign=0.5, wrap=True)
    area.pack_start(title, False, False, 0)
    body = label(ngettext(
        "Mirror makes <b>{dest}</b> match <b>{src}</b>. This file exists only at the destination and will be removed. This cannot be undone.",
        "Mirror makes <b>{dest}</b> match <b>{src}</b>. These {n} files exist only at the destination and will be removed. This cannot be undone.",
        n).format(n=n, dest=esc(dest_label), src=esc(source_label)), "lfc-dim", markup=True, wrap=True, xalign=0.5)
    area.pack_start(body, False, False, 0)
    listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    add_classes(listing, "lfc-card")
    for c in dels[:4]:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.pack_start(add_classes(icon("delta-delete"), "lfc-err"), False, False, 0)
        row.pack_start(label(c.path + ("/" if c.is_dir else ""), "lfc-mono", ellipsize=True), True, True, 0)
        listing.pack_start(row, False, False, 0)
    if n > 4:
        listing.pack_start(label(_("… and {n} more").format(n=n - 4), "lfc-dim"), False, False, 0)
    area.pack_start(listing, False, False, 0)
    dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    ok = dlg.add_button(_("Delete and mirror"), Gtk.ResponseType.OK)
    ok.get_style_context().add_class("destructive-action")
    dlg.set_default_response(Gtk.ResponseType.CANCEL)
    dlg.show_all()
    response = dlg.run()
    dlg.destroy()
    del job_name  # kept in the signature for callers' clarity
    return response == Gtk.ResponseType.OK


def confirm(parent: Gtk.Window | None, title: str, body: str, ok_label: str, destructive: bool = False) -> bool:
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                            buttons=Gtk.ButtonsType.NONE, text=title)
    dlg.format_secondary_text(body)
    dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    ok = dlg.add_button(ok_label, Gtk.ResponseType.OK)
    ok.get_style_context().add_class("destructive-action" if destructive else "suggested-action")
    response = dlg.run()
    dlg.destroy()
    return response == Gtk.ResponseType.OK


def info(parent: Gtk.Window | None, title: str, body: str, error: bool = False) -> None:
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True,
                            message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO,
                            buttons=Gtk.ButtonsType.CLOSE, text=title)
    dlg.format_secondary_text(body)
    dlg.run()
    dlg.destroy()


def empty_state(icon_id: str, title: str, body: str) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_valign(Gtk.Align.CENTER)
    box.set_halign(Gtk.Align.CENTER)
    img = icon(icon_id, SIZE_EMPTY)
    add_classes(img, "lfc-dim")
    box.pack_start(img, False, False, 0)
    box.pack_start(label(title, "lfc-group-title", xalign=0.5), False, False, 0)
    box.pack_start(label(body, "lfc-dim", xalign=0.5, wrap=True), False, False, 0)
    return box
