"""Settings: appearance, safety defaults, notifications, drives and system tools."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from linfilecopy.engine.drives import DriveInfo, visible_drives  # noqa: E402
from linfilecopy.engine.tools import Capabilities  # noqa: E402
from linfilecopy.i18n import _  # noqa: E402
from linfilecopy.model.enums import DriveKind  # noqa: E402
from linfilecopy.model.settings import ACCENTS  # noqa: E402
from linfilecopy.ui.components.component_common import (Segmented, activate_rows, add_classes, boxed_list, clear,  # noqa: E402
                                                        group, label, row, spin, switch_row)
from linfilecopy.ui.components.component_dialogs import info  # noqa: E402
from linfilecopy.ui.components.component_path_card import drive_icon  # noqa: E402
from linfilecopy.ui.icons import button, icon  # noqa: E402
from linfilecopy.ui.pages.page_base import BasePage  # noqa: E402


class SettingsPage(BasePage):
    page_id = "settings"
    title = _("Settings")

    def build_content(self) -> None:
        s = self.ctx.settings
        cols = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=22, homogeneous=True)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)

        # appearance
        lst = boxed_list()
        style = Segmented([("system", _("System"), None), ("light", _("Light"), None), ("dark", _("Dark"), None)],
                          s.style, self._on_style)
        lst.add(row(_("Style"), _("System follows your desktop's light or dark setting"), None, [style]))
        accents = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.accent_buttons: dict[str, Gtk.RadioButton] = {}
        group_btn = None
        for key, colour in ACCENTS.items():
            b = Gtk.RadioButton.new_from_widget(group_btn)
            group_btn = group_btn or b
            b.set_mode(False)
            swatch = Gtk.DrawingArea()
            swatch.set_size_request(18, 18)
            swatch.connect("draw", self._draw_swatch, colour)
            b.add(swatch)
            b.set_tooltip_text(key.capitalize())
            b.get_accessible().set_name(_("Accent colour {name}").format(name=key))
            b.set_active(key == s.accent)
            b.connect("toggled", self._on_accent, key)
            self.accent_buttons[key] = b
            accents.pack_start(b, False, False, 0)
        lst.add(row(_("Accent colour"), None, None, [accents]))
        r, _sw = switch_row(_("Keep running in the tray"), _("Needed for drive and folder triggers after the window is closed"), None,
                            s.keep_in_tray, lambda v: self._save("keep_in_tray", v))
        lst.add(r)
        r, _sw = switch_row(_("Open new jobs in the Simple view"), None, None, s.simple_view_default,
                            lambda v: self._save("simple_view_default", v))
        lst.add(r)
        activate_rows(lst)
        left.pack_start(group(_("Appearance"), "misc-theme", None, lst), False, False, 0)

        # safety
        lst = boxed_list()
        r, _sw = switch_row(_("Preview new jobs first"), _("Recommended while you are learning the app"), None, s.preview_new_jobs,
                            lambda v: self._save("preview_new_jobs", v))
        lst.add(r)
        r, _sw = switch_row(_("Confirm before deleting files"), _("Mirror jobs, and two-way jobs that don't keep a trash folder"), None,
                            s.confirm_deletes, lambda v: self._save("confirm_deletes", v))
        lst.add(r)
        guard = spin(s.twoway_delete_guard_percent, 1, 100, 1, 0, lambda v: self._save("twoway_delete_guard_percent", int(v)))
        guard.get_accessible().set_name(_("Default two-way delete limit"))
        lst.add(row(_("Default two-way delete limit"), _("New two-way jobs stop if more than this share of files would be deleted"), None,
                    [guard, label("%", "lfc-dim")]))
        activate_rows(lst)
        left.pack_start(group(_("Safety"), "action-preview", None, lst), False, False, 0)

        # notifications
        lst = boxed_list()
        r, _sw = switch_row(_("When a job finishes"), None, None, s.notify_success, lambda v: self._save("notify_success", v))
        lst.add(r)
        r, _sw = switch_row(_("When a job fails"), None, None, s.notify_failure, lambda v: self._save("notify_failure", v))
        lst.add(r)
        days = spin(s.history_days, 1, 3650, 1, 0, lambda v: self._save("history_days", int(v)))
        days.get_accessible().set_name(_("Days of history to keep"))
        lst.add(row(_("Keep history and logs for"), None, None, [days, label(_("days"), "lfc-dim")]))
        activate_rows(lst)
        left.pack_start(group(_("Notifications and history"), "feat-notify", None, lst), False, False, 0)
        shortcuts = button("misc-shortcuts", _("Keyboard shortcuts"))
        shortcuts.set_action_name("app.shortcuts")
        shortcuts.set_halign(Gtk.Align.START)
        left.pack_start(shortcuts, False, False, 0)

        # drives
        self.drives_list = boxed_list()
        self.drives_group = group(_("Drives"), "feat-drives", None, self.drives_list)
        sys_row, self.show_system = switch_row(_("Show system partitions"), _("Boot and EFI partitions"), None, s.show_system_partitions,
                                               self._on_show_system)
        sys_list = boxed_list()
        sys_list.add(sys_row)
        activate_rows(sys_list)
        self.drives_group.pack_start(sys_list, False, False, 0)
        right.pack_start(self.drives_group, False, False, 0)

        # tools
        self.tools_list = boxed_list()
        right.pack_start(group(_("System tools"), "misc-command", None, self.tools_list), False, False, 0)
        cols.pack_start(left, True, True, 0)
        cols.pack_start(right, True, True, 0)
        self.cols = cols
        self.content.pack_start(cols, False, False, 0)
        self._narrow = False
        self.connect("size-allocate", self._on_size)

        self.ctx.subscribe("drives", lambda d: self._fill_drives(d))
        self.ctx.subscribe("capabilities", self._fill_tools)
        self.ctx.subscribe("drive-action", self._on_drive_action)
        self._fill_drives(self.ctx.drives.drives if self.ctx.drives else [])
        self.tools_list.add(row(_("Checking tools…"), None, None))

    def _on_size(self, _w: Gtk.Widget, _a: object) -> None:
        narrow = self.get_allocated_width() < 900
        if narrow != self._narrow:
            self._narrow = narrow
            self.cols.set_orientation(Gtk.Orientation.VERTICAL if narrow else Gtk.Orientation.HORIZONTAL)

    # ----- settings -------------------------------------------------------------------
    def _save(self, attr: str, value: object) -> None:
        setattr(self.ctx.settings, attr, value)
        self.ctx.save_settings()

    def _on_style(self, value: str) -> None:
        self._save("style", value)
        self.ctx.theme.apply(self.ctx.settings.style, self.ctx.settings.accent)

    def _on_accent(self, b: Gtk.RadioButton, key: str) -> None:
        if b.get_active():
            self._save("accent", key)
            self.ctx.theme.apply(self.ctx.settings.style, key)

    @staticmethod
    def _draw_swatch(area: Gtk.DrawingArea, cr, colour: str) -> bool:  # type: ignore[no-untyped-def]
        rgba = Gdk.RGBA()
        rgba.parse(colour)
        w, h = area.get_allocated_width(), area.get_allocated_height()
        cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 1)
        cr.arc(w / 2, h / 2, min(w, h) / 2, 0, 6.2832)
        cr.fill()
        return False

    def _on_show_system(self, value: bool) -> None:
        self._save("show_system_partitions", value)
        self._fill_drives(self.ctx.drives.drives if self.ctx.drives else [])

    # ----- drives -------------------------------------------------------------------------
    def _fill_drives(self, drives: list[DriveInfo]) -> None:
        clear(self.drives_list)
        shown = visible_drives(drives, self.ctx.settings.show_system_partitions)
        if not shown:
            self.drives_list.add(row(_("No drives found"), _("UDisks2 is not available, or no drives are connected."), "status-drive-missing"))
        for d in shown:
            buttons = []
            if d.encrypted and d.locked:
                b = button("ep-unlock", _("Unlock"))
                b.connect("clicked", lambda _b, d=d: self._unlock(d))
                buttons.append(b)
            elif not d.mounted:
                b = button("action-browse", _("Mount"))
                b.connect("clicked", lambda _b, d=d: self.ctx.drives.mount(d))
                buttons.append(b)
            if d.kind is DriveKind.REMOVABLE and (d.mounted or d.can_power_off):
                b = button("action-eject", _("Eject"))
                b.connect("clicked", lambda _b, d=d: self.ctx.drives.eject(d))
                buttons.append(b)
            where = d.mount_point or d.device
            summary = d.fs.summary() if not d.encrypted or not d.locked else _("encrypted")
            r = row(d.label, f"{d.describe()} · {summary}\n{where}", drive_icon(d), buttons)
            if d.used_fraction is not None:
                from linfilecopy.ui.components.component_common import capacity_bar, capacity_text

                text_box = r.title_label.get_parent()
                bar = capacity_bar(d.used_fraction, _("{drive}: {p}% used").format(drive=d.label, p=round(d.used_fraction * 100)))
                bar.set_margin_top(4)
                text_box.pack_start(bar, False, False, 0)
                text_box.pack_start(label(capacity_text(d), "lfc-dim", "lfc-small"), False, False, 0)
            self.drives_list.add(r)
        self.drives_list.show_all()

    def _unlock(self, drive: DriveInfo) -> None:
        from linfilecopy.ui.manager_secrets import PassphraseDialog, store

        value, remember = PassphraseDialog(self.ctx.window, drive).ask()
        if value and self.ctx.drives is not None:
            if remember:
                store(drive.uuid, drive.label, value)
            self.ctx.drives.unlock(drive, value)

    def _on_drive_action(self, drive_label: str, error: str | None) -> None:
        if error:
            info(self.ctx.window, _("{drive}: the operation failed").format(drive=drive_label), error, True)

    # ----- tools ---------------------------------------------------------------------------
    def _fill_tools(self, caps: Capabilities) -> None:
        clear(self.tools_list)
        for t in caps.all():
            img = add_classes(icon("status-success" if t.available else "status-missing-tool"), "lfc-ok" if t.available else "lfc-warn")
            title = f"{t.name} {t.version}" if t.version else t.name
            detail = t.purpose + (f" · {t.path}" if t.path and t.available else "")
            if not t.available:
                detail = f"{t.purpose} · {_('not found')}. {t.missing_effect}"
            r = row(title, detail, None)
            r.get_child().pack_start(img, False, False, 0)
            r.get_child().reorder_child(img, 0)
            self.tools_list.add(r)
            if not t.available and t.install:
                for distro, cmd in t.install.items():
                    entry = Gtk.Entry(text=cmd, editable=False)
                    entry.get_style_context().add_class("lfc-mono")
                    entry.set_width_chars(26)
                    copy_btn = button("action-copy-command", None, _("Copy"))
                    copy_btn.connect("clicked", lambda _b, cmd=cmd: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(cmd, -1))
                    self.tools_list.add(row(distro, None, None, [entry, copy_btn], sub=True))
        self.tools_list.show_all()
