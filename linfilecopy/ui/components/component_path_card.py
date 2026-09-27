"""Source / destination card (B1, #20): drive picker, path entry, browse, drag and drop."""
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
from linfilecopy.ui.icons import icon, icon_name  # noqa: E402

KIND_ICON = {DriveKind.INTERNAL: "ep-internal", DriveKind.REMOVABLE: "ep-removable",
             DriveKind.ARRAY: "ep-array", DriveKind.UNKNOWN: "ep-folder"}


def drive_icon(drive: DriveInfo) -> str:
    if drive.encrypted and drive.locked:
        return "ep-encrypted"
    return KIND_ICON.get(drive.kind, "ep-folder")


class PathCardWidget(Gtk.Box):
    """Emits ``changed`` when the endpoint (or copy-contents toggle) changes."""

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
        self._loading = True
        self.endpoint = Endpoint(**ep.__dict__)
        self.entry.set_text(ep.path)
        if self.contents is not None:
            self.contents.set_value("contents" if copy_contents else "itself", notify=False)
        self._loading = False
        self.refresh_drive_info()

    @property
    def copy_contents(self) -> bool:
        return self.contents is None or self.contents.value == "contents"

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
            self.info.set_text(" · ".join(parts))

    def set_drop_hint(self, visible: bool) -> None:
        self.drop_hint.set_visible(visible)

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
        chooser = Gtk.FileChooserNative.new(
            _("Choose the source folder") if self.role == "source" else _("Choose the destination folder"),
            self.get_toplevel(), Gtk.FileChooserAction.SELECT_FOLDER, _("Choose"), _("Cancel"))
        chooser.set_create_folders(self.role == "destination")
        current = self.endpoint.path
        if current and os.path.isdir(current):
            chooser.set_current_folder(current)
        if chooser.run() == Gtk.ResponseType.ACCEPT:
            path = chooser.get_filename()
            if path:
                self._set_path(path)
        chooser.destroy()

    def _on_drive_menu(self, button: Gtk.MenuButton) -> None:
        if not button.get_active():
            return
        for child in self.popover.get_children():
            self.popover.remove(child)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(6)
        drives = visible_drives(self.get_drives())
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
            b.connect("clicked", self._on_drive_chosen, d)
            box.pack_start(b, False, False, 0)
        box.show_all()
        self.popover.add(box)

    def _on_drive_chosen(self, _b: Gtk.Button, drive: DriveInfo) -> None:
        self.popover.popdown()

        def use() -> None:
            fresh = next((x for x in self.get_drives() if x.uuid == drive.uuid or
                          (drive.encrypted and x.container_uuid == drive.uuid)), None)
            if fresh is not None and fresh.mount_point:
                self._set_path(fresh.mount_point)

        if drive.encrypted and drive.locked:
            if self.request_unlock:
                self.request_unlock(drive, use)
        elif not drive.mounted:
            if self.request_mount:
                self.request_mount(drive, use)
        elif drive.mount_point:
            self._set_path(drive.mount_point)

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

    def _on_drop(self, _w: Gtk.Widget, _ctx: Gdk.DragContext, _x: int, _y: int,
                 data: Gtk.SelectionData, _info: int, _time: int) -> None:
        self._set_hot(False)
        for uri in data.get_uris() or []:
            path = Gio.File.new_for_uri(uri).get_path()
            if path and os.path.isdir(path):
                self._set_path(path)
                return
            if path and os.path.isfile(path):
                self._set_path(os.path.dirname(path))
                return
