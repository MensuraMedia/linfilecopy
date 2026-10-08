"""Source / destination card (B1, #20): drive picker, path entry, browse, drag and drop.

The source card can hold more than one folder or drive (multi-source Copy): a
primary row plus any number of extra rows, each removable. The destination is
always a single folder.
"""
from __future__ import annotations

import os
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GObject, Gtk  # noqa: E402

from linfilecopy.engine.drives import DriveInfo, endpoint_for_path, visible_drives  # noqa: E402
from linfilecopy.i18n import _  # noqa: E402
from linfilecopy.model.enums import DriveKind  # noqa: E402
from linfilecopy.model.job import Endpoint  # noqa: E402
from linfilecopy.ui.components.component_common import Segmented, add_classes, label  # noqa: E402
from linfilecopy.ui.icons import button, icon, icon_name  # noqa: E402

KIND_ICON = {DriveKind.INTERNAL: "ep-internal", DriveKind.REMOVABLE: "ep-removable",
             DriveKind.ARRAY: "ep-array", DriveKind.UNKNOWN: "ep-folder"}


def drive_icon(drive: DriveInfo) -> str:
    if drive.encrypted and drive.locked:
        return "ep-encrypted"
    return KIND_ICON.get(drive.kind, "ep-folder")


def _fill_drive_popover(popover: Gtk.Popover, get_drives: Callable[[], list[DriveInfo]],
                        on_choose: Callable[[DriveInfo], None]) -> None:
    """(Re)build a drive-picker popover. Shared by the primary and extra rows."""
    for child in popover.get_children():
        popover.remove(child)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    for side in ("top", "bottom", "start", "end"):
        getattr(box, f"set_margin_{side}")(6)
    drives = visible_drives(get_drives())
    if not drives:
        box.pack_start(label(_("No drives found. Use Browse to pick a folder."), "lfc-dim", wrap=True), False, False, 6)
    for d in drives:
        b = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.pack_start(icon(drive_icon(d)), False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        text.pack_start(label(d.label), False, False, 0)
        text.pack_start(label(d.describe(), "lfc-dim", "lfc-small"), False, False, 0)
        row.pack_start(text, True, True, 0)
        b.add(row)
        b.connect("clicked", lambda _b, drive=d: on_choose(drive))
        box.pack_start(b, False, False, 0)
    box.show_all()
    popover.add(box)


def _choose_folder(parent: Gtk.Widget | None, role: str, current: str, on_path: Callable[[str], None]) -> None:
    chooser = Gtk.FileChooserNative.new(
        _("Choose the source folder") if role == "source" else _("Choose the destination folder"),
        parent, Gtk.FileChooserAction.SELECT_FOLDER, _("Choose"), _("Cancel"))
    chooser.set_create_folders(role == "destination")
    if current and os.path.isdir(current):
        chooser.set_current_folder(current)
    if chooser.run() == Gtk.ResponseType.ACCEPT:
        path = chooser.get_filename()
        if path:
            on_path(path)
    chooser.destroy()


def _resolve_drive_choice(drive: DriveInfo, get_drives: Callable[[], list[DriveInfo]],
                          request_unlock: Callable[[DriveInfo, Callable[[], None]], None] | None,
                          request_mount: Callable[[DriveInfo, Callable[[], None]], None] | None,
                          on_path: Callable[[str], None]) -> None:
    """Unlock/mount the chosen drive if needed, then hand its mount point to ``on_path``."""
    def use() -> None:
        fresh = next((x for x in get_drives() if x.uuid == drive.uuid or
                      (drive.encrypted and x.container_uuid == drive.uuid)), None)
        if fresh is not None and fresh.mount_point:
            on_path(fresh.mount_point)

    if drive.encrypted and drive.locked:
        if request_unlock:
            request_unlock(drive, use)
    elif not drive.mounted:
        if request_mount:
            request_mount(drive, use)
    elif drive.mount_point:
        on_path(drive.mount_point)


class _ExtraSourceRow(Gtk.Box):
    """One extra source folder/drive: drive picker + path entry + browse + remove."""

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "removed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, get_drives: Callable[[], list[DriveInfo]],
                 request_unlock: Callable[[DriveInfo, Callable[[], None]], None] | None,
                 request_mount: Callable[[DriveInfo, Callable[[], None]], None] | None) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.get_drives = get_drives
        self.request_unlock = request_unlock
        self.request_mount = request_mount
        self.endpoint = Endpoint()
        self._loading = False
        add_classes(self, "lfc-extra-source")

        self.drive_button = Gtk.MenuButton()
        db = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.drive_icon = icon("ep-folder")
        self.drive_label = label(_("Folder"))
        self.drive_label.set_max_width_chars(14)
        self.drive_label.set_ellipsize(3)
        db.pack_start(self.drive_icon, False, False, 0)
        db.pack_start(self.drive_label, False, False, 0)
        db.pack_start(icon("action-collapse", 12), False, False, 0)
        self.drive_button.add(db)
        self.drive_button.set_tooltip_text(_("Choose a drive"))
        self.popover = Gtk.Popover()
        self.drive_button.set_popover(self.popover)
        self.drive_button.connect("toggled", self._on_drive_menu)
        self.pack_start(self.drive_button, False, False, 0)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text(_("Another source folder"))
        self.entry.get_accessible().set_name(_("Extra source folder"))
        self.entry.connect("activate", lambda _e: self._commit_entry())
        self.entry.connect("focus-out-event", lambda *_a: self._commit_entry() or False)
        self.pack_start(self.entry, True, True, 0)

        browse = Gtk.Button()
        browse.add(icon("action-browse"))
        browse.set_tooltip_text(_("Browse for a folder"))
        browse.connect("clicked", lambda _b: _choose_folder(self.get_toplevel(), "source", self.endpoint.path, self._set_path))
        self.pack_start(browse, False, False, 0)

        remove = button("action-close", None, _("Remove this source"))
        remove.connect("clicked", lambda _b: self.emit("removed"))
        self.pack_start(remove, False, False, 0)

    def set_endpoint(self, ep: Endpoint) -> None:
        self._loading = True
        self.endpoint = Endpoint(**ep.__dict__)
        self.entry.set_text(ep.path)
        self._loading = False
        self.refresh_drive_info()

    def refresh_drive_info(self) -> None:
        drives = self.get_drives()
        drive = next((d for d in drives if self.endpoint.volume_uuid and d.uuid == self.endpoint.volume_uuid), None)
        if drive is not None:
            self.drive_icon.set_from_icon_name(icon_name(drive_icon(drive)), Gtk.IconSize.BUTTON)
            self.drive_label.set_text(drive.label)
        elif self.endpoint.volume_uuid:
            self.drive_icon.set_from_icon_name(icon_name("status-drive-missing"), Gtk.IconSize.BUTTON)
            self.drive_label.set_text(self.endpoint.volume_label or _("Drive"))
        else:
            self.drive_icon.set_from_icon_name(icon_name(KIND_ICON.get(self.endpoint.kind, "ep-folder")), Gtk.IconSize.BUTTON)
            self.drive_label.set_text(self.endpoint.volume_label or _("Folder"))

    def _set_path(self, path: str) -> None:
        path = os.path.normpath(os.path.expanduser(path.strip())) if path.strip() else ""
        self.endpoint = endpoint_for_path(path, self.get_drives()) if path else Endpoint()
        self._loading = True
        self.entry.set_text(path)
        self._loading = False
        self.refresh_drive_info()
        if not self._loading:
            self.emit("changed")

    def _commit_entry(self) -> None:
        text = self.entry.get_text()
        normalised = os.path.normpath(os.path.expanduser(text.strip())) if text.strip() else ""
        if normalised != (self.endpoint.path or ""):
            self._set_path(text)

    def _on_drive_menu(self, button: Gtk.MenuButton) -> None:
        if not button.get_active():
            return
        _fill_drive_popover(self.popover, self.get_drives, self._on_drive_chosen)

    def _on_drive_chosen(self, drive: DriveInfo) -> None:
        self.popover.popdown()
        _resolve_drive_choice(drive, self.get_drives, self.request_unlock, self.request_mount, self._set_path)


class PathCardWidget(Gtk.Box):
    """Emits ``changed`` when any endpoint (or the copy-contents toggle) changes.

    For the source role the card holds a primary folder plus any number of extra
    folders/drives; :attr:`extra_endpoints` lists the extra ones.
    """

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, role: str, get_drives: Callable[[], list[DriveInfo]],
                 request_unlock: Callable[[DriveInfo, Callable[[], None]], None] | None = None,
                 request_mount: Callable[[DriveInfo, Callable[[], None]], None] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.role = role
        self.get_drives = get_drives
        self.request_unlock = request_unlock
        self.request_mount = request_mount
        self.endpoint = Endpoint()
        self._loading = False
        self._extra_rows: list[_ExtraSourceRow] = []
        add_classes(self, "lfc-path-card", role)
        is_source = role == "source"

        caption = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        cap_icon = icon("ep-source" if is_source else "ep-destination")
        caption.pack_start(cap_icon, False, False, 0)
        caption.pack_start(label(_("FROM · SOURCE") if is_source else _("TO · DESTINATION"), "lfc-caption"), False, False, 0)
        self.info = label("", "lfc-dim", "lfc-small", xalign=1.0, ellipsize=True)
        caption.pack_end(self.info, True, True, 0)
        self.pack_start(caption, False, False, 0)

        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.drive_button = Gtk.MenuButton()
        db = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.drive_icon = icon("ep-folder")
        self.drive_label = label(_("Folder"))
        self.drive_label.set_max_width_chars(16)
        self.drive_label.set_ellipsize(3)
        db.pack_start(self.drive_icon, False, False, 0)
        db.pack_start(self.drive_label, False, False, 0)
        db.pack_start(icon("action-collapse", 12), False, False, 0)
        self.drive_button.add(db)
        self.drive_button.set_tooltip_text(_("Choose a drive"))
        self.drive_button.get_accessible().set_name(_("Choose a drive for the {role}").format(
            role=_("source") if is_source else _("destination")))
        self.popover = Gtk.Popover()
        self.drive_button.set_popover(self.popover)
        self.drive_button.connect("toggled", self._on_drive_menu)
        line.pack_start(self.drive_button, False, False, 0)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text(_("Drop a folder here or press Browse"))
        self.entry.get_accessible().set_name(_("Source folder") if is_source else _("Destination folder"))
        self.entry.connect("activate", lambda _e: self._commit_entry())
        self.entry.connect("focus-out-event", lambda *_a: self._commit_entry() or False)
        line.pack_start(self.entry, True, True, 0)
        browse = Gtk.Button()
        browse.add(icon("action-browse"))
        browse.set_tooltip_text(_("Browse for a folder"))
        browse.get_accessible().set_name(_("Browse for a folder"))
        browse.connect("clicked", self._on_browse)
        line.pack_start(browse, False, False, 0)
        self.pack_start(line, False, False, 0)

        # Extra source rows (source only) live in their own container, with an "add" button.
        self.extras_box: Gtk.Box | None = None
        self.add_source_button: Gtk.Button | None = None
        if is_source:
            self.extras_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            self.pack_start(self.extras_box, False, False, 0)
            add_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            self.add_source_button = Gtk.Button()
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            inner.pack_start(icon("action-new", 14), False, False, 0)
            inner.pack_start(label(_("Add another source folder")), False, False, 0)
            self.add_source_button.add(inner)
            add_classes(self.add_source_button, "lfc-add-source")
            self.add_source_button.set_tooltip_text(_("Copy several folders or drives into the one destination"))
            self.add_source_button.connect("clicked", lambda _b: self._add_extra_row(focus=True))
            add_row.pack_start(self.add_source_button, False, False, 0)
            self.pack_start(add_row, False, False, 0)

        self.drop_hint = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        add_classes(self.drop_hint, "lfc-drop-hint")
        self.drop_hint.pack_start(icon("action-drop"), False, False, 0)
        self.drop_label = label(_("Drag a folder from your file manager onto this card"), "lfc-small")
        self.drop_hint.pack_start(self.drop_label, True, True, 0)
        self.drop_hint.set_no_show_all(True)
        self.pack_start(self.drop_hint, False, False, 0)

        self.contents: Segmented | None = None
        if is_source:
            self.contents = Segmented(
                [("itself", _("Copy the folder itself"), None), ("contents", _("Copy what is inside it"), None)],
                "contents", lambda _v: self._emit(),
                tooltips={"itself": _("Creates a folder with the same name inside the destination."),
                          "contents": _("Puts the files straight into the destination folder.")})
            self.pack_start(self.contents, False, False, 0)

        self.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY)
        self.connect("drag-data-received", self._on_drop)
        self.connect("drag-motion", self._on_drag_motion)
        self.connect("drag-leave", lambda *_a: self._set_hot(False))

    # ----- public ----------------------------------------------------------------
    def set_endpoint(self, ep: Endpoint, copy_contents: bool = True) -> None:
        """Single-source set (destination, or a source with no extras)."""
        self.set_sources(ep, [], copy_contents)

    def set_sources(self, primary: Endpoint, extras: list[Endpoint] | None = None,
                    copy_contents: bool = True) -> None:
        self._loading = True
        self.endpoint = Endpoint(**primary.__dict__)
        self.entry.set_text(primary.path)
        if self.contents is not None:
            self.contents.set_value("contents" if copy_contents else "itself", notify=False)
        self._clear_extra_rows()
        for ep in (extras or []):
            if (ep.path or "").strip():
                self._add_extra_row(ep)
        self._loading = False
        self.refresh_drive_info()

    @property
    def copy_contents(self) -> bool:
        return self.contents is None or self.contents.value == "contents"

    @property
    def extra_endpoints(self) -> list[Endpoint]:
        """Extra source endpoints that have a path (primary is :attr:`endpoint`)."""
        return [r.endpoint for r in self._extra_rows if (r.endpoint.path or "").strip()]

    def refresh_drive_info(self) -> None:
        """Update the drive button and caption from the current drive list."""
        drives = self.get_drives()
        drive = next((d for d in drives if self.endpoint.volume_uuid and d.uuid == self.endpoint.volume_uuid), None)
        if drive is not None:
            self.drive_icon.set_from_icon_name(icon_name(drive_icon(drive)), Gtk.IconSize.BUTTON)
            self.drive_label.set_text(drive.label)
            self.info.set_text(drive.describe())
        elif self.endpoint.volume_uuid:
            self.drive_icon.set_from_icon_name(icon_name("status-drive-missing"), Gtk.IconSize.BUTTON)
            self.drive_label.set_text(self.endpoint.volume_label or _("Drive"))
            self.info.set_text(_("Not connected"))
        else:
            ep = self.endpoint
            self.drive_icon.set_from_icon_name(icon_name(KIND_ICON.get(ep.kind, "ep-folder")), Gtk.IconSize.BUTTON)
            self.drive_label.set_text(ep.volume_label or _("Folder"))
            parts = []
            if ep.kind is DriveKind.INTERNAL:
                parts.append(_("Internal"))
            if ep.fs_type:
                from linfilecopy.engine.filesystems import capabilities_for

                parts.append(capabilities_for(ep.fs_type).label)
            n_extra = len(self.extra_endpoints)
            if n_extra:
                parts.append(_("+{n} more source(s)").format(n=n_extra))
            self.info.set_text(" · ".join(parts))
        for r in self._extra_rows:
            r.refresh_drive_info()

    def set_drop_hint(self, visible: bool) -> None:
        self.drop_hint.set_visible(visible)

    # ----- extra rows ---------------------------------------------------------------
    def _add_extra_row(self, ep: Endpoint | None = None, focus: bool = False) -> _ExtraSourceRow:
        row = _ExtraSourceRow(self.get_drives, self.request_unlock, self.request_mount)
        if ep is not None:
            row.set_endpoint(ep)
        row.connect("changed", lambda _r: self._emit())
        row.connect("removed", self._on_remove_extra)
        self._extra_rows.append(row)
        if self.extras_box is not None:
            self.extras_box.pack_start(row, False, False, 0)
            row.show_all()
        if focus:
            row.entry.grab_focus()
        return row

    def _on_remove_extra(self, row: _ExtraSourceRow) -> None:
        if row in self._extra_rows:
            self._extra_rows.remove(row)
        if self.extras_box is not None:
            self.extras_box.remove(row)
        self.refresh_drive_info()
        self._emit()

    def _clear_extra_rows(self) -> None:
        for row in list(self._extra_rows):
            if self.extras_box is not None:
                self.extras_box.remove(row)
        self._extra_rows.clear()

    # ----- internals ---------------------------------------------------------------
    def _emit(self) -> None:
        if not self._loading:
            self.emit("changed")

    def _set_path(self, path: str) -> None:
        path = os.path.normpath(os.path.expanduser(path.strip())) if path.strip() else ""
        self.endpoint = endpoint_for_path(path, self.get_drives()) if path else Endpoint()
        self._loading = True
        self.entry.set_text(path)
        self._loading = False
        self.refresh_drive_info()
        self._emit()

    def _commit_entry(self) -> None:
        text = self.entry.get_text()
        normalised = os.path.normpath(os.path.expanduser(text.strip())) if text.strip() else ""
        if normalised != (self.endpoint.path or ""):
            self._set_path(text)

    def _on_browse(self, _btn: Gtk.Button) -> None:
        _choose_folder(self.get_toplevel(), self.role, self.endpoint.path, self._set_path)

    def _on_drive_menu(self, button: Gtk.MenuButton) -> None:
        if not button.get_active():
            return
        _fill_drive_popover(self.popover, self.get_drives, self._on_drive_chosen)

    def _on_drive_chosen(self, drive: DriveInfo) -> None:
        self.popover.popdown()
        _resolve_drive_choice(drive, self.get_drives, self.request_unlock, self.request_mount, self._set_path)

    def _set_hot(self, hot: bool) -> None:
        ctx = self.drop_hint.get_style_context()
        if hot:
            ctx.add_class("active")
            self.drop_label.set_text(_("Release to use this folder"))
            self.drop_hint.set_visible(True)
        else:
            ctx.remove_class("active")
            self.drop_label.set_text(_("Drag a folder from your file manager onto this card"))

    def _on_drag_motion(self, *_args: object) -> bool:
        self._set_hot(True)
        return False

    def _use_dropped(self, path: str) -> None:
        """Set the primary folder, or append an extra source when the primary is taken."""
        if self.role == "source" and (self.endpoint.path or "").strip():
            row = self._add_extra_row()
            row._set_path(path)
        else:
            self._set_path(path)

    def _on_drop(self, _w: Gtk.Widget, _ctx: Gdk.DragContext, _x: int, _y: int,
                 data: Gtk.SelectionData, _info: int, _time: int) -> None:
        self._set_hot(False)
        for uri in data.get_uris() or []:
            path = Gio.File.new_for_uri(uri).get_path()
            if path and os.path.isdir(path):
                self._use_dropped(path)
            elif path and os.path.isfile(path):
                self._use_dropped(os.path.dirname(path))
