"""Job Designer: every feature as a control, live command preview, validation, run.

Simple view = the ten basic features (B1–B10). Advanced view adds a section
per feature group (#1–#20). Every control writes straight into ``self.job``
and triggers a debounced re-plan on a worker thread; the plan feeds the
command preview, the issues panel and the Start button.
"""
from __future__ import annotations

import copy
import os
import threading
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from linfilecopy.engine import planner  # noqa: E402
from linfilecopy.engine.drives import DriveInfo  # noqa: E402
from linfilecopy.engine.filtermatch import FilterMatcher  # noqa: E402
from linfilecopy.engine.planner import Plan  # noqa: E402
from linfilecopy.i18n import _  # noqa: E402
from linfilecopy.model.enums import (CompareMethod, ConflictPolicy, DriveKind, ExcludePreset, LogLevel, Mode,  # noqa: E402
                                     OverwritePolicy, ScheduleKind, SpeedUnit, SymlinkPolicy, Trigger)
from linfilecopy.model.job import SyncJob  # noqa: E402
from linfilecopy.model.templates import blank_job, load_templates  # noqa: E402
from linfilecopy.model.validation import INFO  # noqa: E402
from linfilecopy.ui.components.component_common import (MessageBar, Segmented, activate_rows, add_classes,  # noqa: E402
                                                        boxed_list, combo, format_bytes, group, label, row, spin,
                                                        switch, switch_row)
from linfilecopy.ui import manager_launch as launch  # noqa: E402
from linfilecopy.ui.components.component_dialogs import confirm, info  # noqa: E402
from linfilecopy.ui.components.component_filter_editor import FilterEditorWidget  # noqa: E402
from linfilecopy.ui.components.component_panels import CommandPreviewWidget, IssuesWidget, Section  # noqa: E402
from linfilecopy.ui.components.component_path_card import PathCardWidget  # noqa: E402
from linfilecopy.ui.icons import button, icon  # noqa: E402
from linfilecopy.ui.pages.page_base import BasePage  # noqa: E402

REPLAN_DELAY_MS = 250
SIDE_WIDTH = 360
STACK_BELOW = 900   # page width under which the side panel moves below the form

MODE_TEXT = {
    Mode.COPY: _("Copy adds new files and updates changed ones. Nothing at the destination is deleted."),
    Mode.MIRROR: _("Mirror makes the destination identical to the source: files that exist only at the destination are deleted after you confirm."),
    Mode.TWO_WAY: _("Two-way keeps both folders in step: changes and deletions on either side are copied to the other. Deleted files are kept in .lfc-trash."),
}
PRESET_TEXT = {
    ExcludePreset.HIDDEN: (_("Hidden files"), "preset-hidden", _("Files and folders whose names start with a dot")),
    ExcludePreset.CACHE: (_("Cache folders"), "preset-cache", _(".cache, __pycache__, node_modules, thumbnails")),
    ExcludePreset.TEMP: (_("Temp files"), "preset-temp", _("*.tmp, *~, lock files, partial downloads")),
    ExcludePreset.SYSTEM: (_("System folders"), "preset-system", _("lost+found, trash, System Volume Information, .DS_Store")),
}


class DesignerPage(BasePage):
    page_id = "designer"
    title = _("Job Designer")

    def __init__(self, ctx) -> None:  # type: ignore[no-untyped-def]
        self.job: SyncJob = blank_job(ctx.settings.preview_new_jobs)
        self.saved_snapshot: dict | None = None
        self.plan: Plan | None = None
        self._loading = False
        self._syncers: list[Callable[[], None]] = []
        self._replan_id = 0
        self._plan_seq = 0
        self._advanced_widgets: list[Gtk.Widget] = []
        self._stacked = False
        super().__init__(ctx, scroll=False)
        ctx.subscribe("drives", lambda _d: self._on_drives())
        ctx.subscribe("capabilities", lambda _c: self._schedule_replan())
        ctx.subscribe("action", self._on_action)
        ctx.subscribe("edit-job", self.load_job)
        ctx.subscribe("new-from-template", self._new_from_template)
        ctx.subscribe("preview-mode", lambda on: self._update_start_label())
        ctx.subscribe("jobs-changed", lambda: self._rebuild_job_menu())
        ctx.subscribe("schedules-changed", self._sync_schedule_from_store)
        self._load_initial_job()

    # =====================================================================
    # layout
    def build_content(self) -> None:
        self.content.set_spacing(14)
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.job_menu = Gtk.MenuButton()
        jm = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        jm.pack_start(icon("action-open-job"), False, False, 0)
        jm.pack_start(Gtk.Label(label=_("Jobs")), False, False, 0)
        jm.pack_start(icon("action-collapse", 12), False, False, 0)
        self.job_menu.add(jm)
        self.job_menu.set_tooltip_text(_("Open a saved job"))
        self.job_popover = Gtk.Popover()
        self.job_menu.set_popover(self.job_popover)
        top.pack_start(self.job_menu, False, False, 0)
        self.name_entry = Gtk.Entry()
        self.name_entry.set_width_chars(12)
        self.name_entry.set_hexpand(True)
        self.name_entry.set_placeholder_text(_("Job name"))
        self.name_entry.get_accessible().set_name(_("Job name"))
        self.name_entry.connect("changed", self._on_name)
        top.pack_start(self.name_entry, True, True, 0)
        self.view_switch = Segmented([("simple", _("Simple"), None), ("advanced", _("Advanced"), None)],
                                     "simple" if self.ctx.settings.simple_view_default else "advanced",
                                     lambda v: self._set_view(v))
        more = Gtk.MenuButton()
        more.add(icon("action-more"))
        more.set_tooltip_text(_("More job actions"))
        more.get_accessible().set_name(_("More job actions"))
        more.set_popover(self._build_more_popover())
        top.pack_end(more, False, False, 0)
        save = button("action-save", _("Save"), _("Save the job (Ctrl+S)"))
        save.connect("clicked", lambda _b: self.save_job())
        top.pack_end(save, False, False, 0)
        top.pack_end(self.view_switch, False, False, 12)
        self.content.pack_start(top, False, False, 0)

        # form and side panel
        self.form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.form.set_margin_end(6)
        self._build_simple()
        self._build_advanced()
        self.side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.command = CommandPreviewWidget()
        self.issues = IssuesWidget()
        self.side.pack_start(self.command, False, False, 0)
        self.side.pack_start(self.issues, False, False, 0)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_halign(Gtk.Align.END)
        self.preview_button = button("action-preview", _("Preview"), _("Show what would change, without changing anything (Ctrl+Shift+P)"), "lfc-big")
        self.preview_button.connect("clicked", lambda _b: self.preview())
        self.start_button = button("action-start", _("Start"), _("Run the job now (Ctrl+Return)"), "suggested-action")
        add_classes(self.start_button, "lfc-big")
        self.start_button.connect("clicked", lambda _b: self.start())
        actions.pack_start(self.preview_button, False, False, 0)
        actions.pack_start(self.start_button, False, False, 0)
        self.side.pack_start(actions, False, False, 0)
        self.side.set_size_request(SIDE_WIDTH, -1)

        self.form_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        self.form_scroll.add(self.form)
        # The side panel keeps its full width; only the form may shrink (and re-flow).
        self.side_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.side_scroll.add(self.side)
        self.body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=22)
        self.body.pack_start(self.form_scroll, True, True, 0)
        self.body.pack_start(self.side_scroll, False, False, 0)
        self.content.pack_start(self.body, True, True, 0)
        self.connect("size-allocate", self._on_size)

    def _on_size(self, _w: Gtk.Widget, _alloc: object) -> None:
        stacked = self.get_allocated_width() < STACK_BELOW
        if stacked != self._stacked:
            self._stacked = stacked
            GLib.idle_add(self._restack, stacked)

    def _restack(self, stacked: bool) -> bool:
        """Narrow windows: the side panel goes below the form in one scroller."""
        if stacked:
            self.side_scroll.remove(self.side)
            self.body.remove(self.side_scroll)
            self.form.pack_start(self.side, False, False, 0)
            self.side.set_size_request(-1, -1)
        else:
            self.form.remove(self.side)
            self.side_scroll.add(self.side)
            self.body.pack_start(self.side_scroll, False, False, 0)
            self.side.set_size_request(SIDE_WIDTH, -1)
        self.body.show_all()
        self._set_view(self.view_switch.value)
        return GLib.SOURCE_REMOVE

    # ----- binding helpers ----------------------------------------------------------
    def _sync(self, fn: Callable[[], None]) -> None:
        self._syncers.append(fn)

    def _bind_switch(self, title: str, subtitle: str | None, icon_id: str | None, get: Callable[[], bool],
                     set_: Callable[[bool], None], sub: bool = False, tooltip: str | None = None) -> tuple[Gtk.ListBoxRow, Gtk.Switch]:
        def changed(value: bool) -> None:
            if not self._loading:
                set_(value)
                self._changed()

        r, sw = switch_row(title, subtitle, icon_id, get(), changed, sub=sub, tooltip=tooltip)
        self._sync(lambda: sw.set_active(get()))
        return r, sw

    def _bind_spin(self, value: Callable[[], float], set_: Callable[[float], None], lo: float, hi: float,
                   step: float = 1, digits: int = 0, name: str = "") -> Gtk.SpinButton:
        def changed(v: float) -> None:
            if not self._loading:
                set_(v)
                self._changed()

        sb = spin(value(), lo, hi, step, digits, changed)
        if name:
            sb.get_accessible().set_name(name)
        self._sync(lambda: sb.set_value(value()))
        return sb

    def _bind_combo(self, options: list[tuple[str, str]], get: Callable[[], str], set_: Callable[[str], None],
                    name: str = "") -> Gtk.ComboBoxText:
        def changed(v: str) -> None:
            if not self._loading and v:
                set_(v)
                self._changed()

        cb = combo(options, get(), changed)
        if name:
            cb.get_accessible().set_name(name)
        self._sync(lambda: cb.set_active_id(get()))
        return cb

    # ----- Simple view (B1–B10) ---------------------------------------------------------
    def _build_simple(self) -> None:
        drives = lambda: self.ctx.drives.drives if self.ctx.drives else []  # noqa: E731
        self.src_card = PathCardWidget("source", drives, self._request_unlock, self._request_mount)
        self.src_card.connect("changed", self._on_source_changed)
        self.dst_card = PathCardWidget("destination", drives, self._request_unlock, self._request_mount)
        self.dst_card.connect("changed", self._on_dest_changed)
        self.form.pack_start(self.src_card, False, False, 0)
        swap = button("action-swap", None, _("Swap source and destination"))
        swap.set_halign(Gtk.Align.CENTER)
        swap.connect("clicked", self._on_swap)
        swap_row = Gtk.Box()
        swap_row.set_center_widget(swap)
        self.form.pack_start(swap_row, False, False, 0)
        self.form.pack_start(self.dst_card, False, False, 0)
        self.fs_message = MessageBar("info", "misc-info")
        self.form.pack_start(self.fs_message, False, False, 0)

        # B2 mode
        self.mode = Segmented([(Mode.COPY.value, _("Copy"), "mode-copy"), (Mode.MIRROR.value, _("Mirror"), "mode-mirror"),
                               (Mode.TWO_WAY.value, _("Two-way"), "mode-twoway")],
                              self.job.mode.value, self._on_mode,
                              tooltips={Mode.COPY.value: _("Copy new and changed files. Never deletes."),
                                        Mode.MIRROR.value: _("Make the destination identical. Deletes extra files (asks first)."),
                                        Mode.TWO_WAY.value: _("Keep both folders in step in both directions.")})
        self.mode_text = label("", "lfc-dim", "lfc-small", wrap=True)
        self.mirror_warning = MessageBar("", "status-missing-tool")
        self.form.pack_start(group(_("What should happen?"), None, None, self.mode, self.mode_text, self.mirror_warning), False, False, 0)
        self._sync(lambda: self.mode.set_value(self.job.mode.value, notify=False))

        # B9 overwrite
        self.overwrite = Segmented([(OverwritePolicy.ALWAYS.value, _("Overwrite"), "policy-overwrite"),
                                    (OverwritePolicy.SKIP.value, _("Skip"), "policy-skip"),
                                    (OverwritePolicy.NEWER.value, _("Overwrite if newer"), "policy-newer")],
                                   self.job.overwrite.value, self._on_overwrite,
                                   tooltips={OverwritePolicy.ALWAYS.value: _("Replace files that differ"),
                                             OverwritePolicy.SKIP.value: _("Never replace a file that already exists"),
                                             OverwritePolicy.NEWER.value: _("Replace only when the source file is newer")})
        self.overwrite_group = group(_("When a file already exists"), None, None, self.overwrite)
        self.form.pack_start(self.overwrite_group, False, False, 0)
        self._sync(lambda: self.overwrite.set_value(self.job.overwrite.value, notify=False))

        # B6 presets
        chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6, column_spacing=8, row_spacing=8)
        chips.set_homogeneous(False)
        self.chips: dict[ExcludePreset, Gtk.ToggleButton] = {}
        for preset, (text, icon_id, tip) in PRESET_TEXT.items():
            tb = Gtk.ToggleButton()
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            inner.pack_start(icon(icon_id), False, False, 0)
            inner.pack_start(Gtk.Label(label=text), False, False, 0)
            tb.add(inner)
            tb.set_tooltip_text(tip)
            tb.get_accessible().set_name(_("Skip {what}").format(what=text))
            add_classes(tb, "lfc-chip")
            tb.connect("toggled", self._on_preset, preset)
            self.chips[preset] = tb
            chips.add(tb)
        custom = button("preset-custom", _("Custom…"), _("Add your own include and exclude rules"))
        add_classes(custom, "lfc-chip")
        custom.connect("clicked", lambda _b: self._open_section("filters"))
        chips.add(custom)
        self.form.pack_start(group(_("Skip these"), None, None, chips), False, False, 0)
        self._sync(lambda: [tb.set_active(p in self.job.filters.presets) for p, tb in self.chips.items()])

        # B5, B7, B10, eject
        basics = boxed_list()
        r, _sw = self._bind_switch(_("Keep dates and permissions"), _("Files keep their modification time and access rights"),
                                   "feat-metadata", lambda: self.job.metadata.basic, lambda v: self.job.metadata.set_basic(v))
        self.basic_meta_row = r
        basics.add(r)
        r, _sw = self._bind_switch(_("Always preview first"), _("Show the list of changes before copying"), "action-preview",
                                   lambda: self.job.preview_first, lambda v: setattr(self.job, "preview_first", v))
        basics.add(r)
        r, _sw = self._bind_switch(_("Notify me when it finishes"), _("Desktop notification on success or failure"), "feat-notify",
                                   lambda: self.job.logging.notify_success and self.job.logging.notify_failure,
                                   lambda v: (setattr(self.job.logging, "notify_success", v), setattr(self.job.logging, "notify_failure", v)))
        basics.add(r)
        self.eject_row, _sw = self._bind_switch(_("Eject the drive when finished"), _("Safe to unplug as soon as the notification appears"),
                                                "action-eject", lambda: self.job.drive.eject_after,
                                                lambda v: setattr(self.job.drive, "eject_after", v))
        basics.add(self.eject_row)
        activate_rows(basics)
        self.form.pack_start(basics, False, False, 0)

    # ----- Advanced view (#1–#20) ---------------------------------------------------------
    def _section(self, key: str, icon_id: str, title: str, note: str) -> Section:
        sec = Section(icon_id, title, note, expanded=False)
        sec.key = key  # type: ignore[attr-defined]
        self.form.pack_start(sec, False, False, 0)
        self._advanced_widgets.append(sec)
        self.sections[key] = sec
        return sec

    def _build_advanced(self) -> None:
        self.sections: dict[str, Section] = {}
        adv_label = label(_("ADVANCED OPTIONS"), "lfc-caption", "lfc-dim")
        adv_label.set_margin_top(6)
        self.form.pack_start(adv_label, False, False, 0)
        self._advanced_widgets.append(adv_label)
        j = lambda: self.job  # noqa: E731

        # Drives (#10, #20)
        sec = self._section("drives", "feat-drives", _("Drives"), "#10 #20")
        lst = boxed_list()
        r, self.unlock_switch = self._bind_switch(_("Unlock the encrypted drive before running"), _("For LUKS-encrypted drives. The passphrase is never saved in the job."),
                                                  "ep-encrypted", lambda: j().drive.unlock_encrypted, lambda v: setattr(j().drive, "unlock_encrypted", v))
        lst.add(r)
        r, _s = self._bind_switch(_("Remember the passphrase in the keyring"), _("Needed for scheduled runs while you are away"), "ep-password",
                                  lambda: j().drive.remember_passphrase, lambda v: setattr(j().drive, "remember_passphrase", v), sub=True)
        lst.add(r)
        r, _s = self._bind_switch(_("Lock and unmount when finished"), None, None,
                                  lambda: j().drive.lock_after, lambda v: setattr(j().drive, "lock_after", v), sub=True)
        lst.add(r)
        wait_spin = self._bind_spin(lambda: j().drive.wait_minutes, lambda v: setattr(j().drive, "wait_minutes", int(v)), 1, 240, name=_("Minutes to wait"))
        wait_sw = switch(j().drive.wait_for_drive, lambda v: None if self._loading else (setattr(j().drive, "wait_for_drive", v), self._changed()))
        self._sync(lambda: wait_sw.set_active(j().drive.wait_for_drive))
        lst.add(row(_("Wait for the drive if it is not connected"), _("Otherwise the run fails with \"Connect the drive\""), "status-drive-missing",
                    [wait_spin, label(_("min"), "lfc-dim"), wait_sw], activatable_widget=wait_sw))
        activate_rows(lst)
        sec.body.pack_start(lst, False, False, 0)

        # Transfer (#1 #2 #7 #8 #15)
        sec = self._section("transfer", "feat-delta", _("Transfer"), "#1 #2 #7 #8 #15")
        lst = boxed_list()
        r, _s = self._bind_switch(_("Delta transfer"), _("Off by default for local copies. Turn on for large files that change a little, like VM images."),
                                  "feat-delta", lambda: j().transfer.delta, lambda v: setattr(j().transfer, "delta", v))
        lst.add(r)
        r, self.inplace_switch = self._bind_switch(_("Update files in place"), _("Saves space for huge files; a crash can leave a file half-updated"), None,
                                                   lambda: j().transfer.inplace, lambda v: setattr(j().transfer, "inplace", v), sub=True)
        lst.add(r)
        cmp = self._bind_combo([(CompareMethod.SIZE_TIME.value, _("Size and modification time")), (CompareMethod.SIZE_ONLY.value, _("Size only"))],
                               lambda: j().transfer.compare.value, lambda v: setattr(j().transfer, "compare", CompareMethod(v)), _("Decide what changed by"))
        lst.add(row(_("Decide what changed by"), None, "feat-incremental", [cmp]))
        r, _s = self._bind_switch(_("Resume interrupted files"), _("Partial files are kept in .lfc-partial and continued next time"), "feat-resume",
                                  lambda: j().transfer.resume, lambda v: setattr(j().transfer, "resume", v))
        lst.add(r)
        r, _s = self._bind_switch(_("Verify with checksums"), _("Slower: reads every file on both sides"), "feat-checksum",
                                  lambda: j().transfer.checksum, lambda v: setattr(j().transfer, "checksum", v))
        lst.add(r)
        r, _s = self._bind_switch(_("Handle sparse files"), _("Virtual-machine disks and databases"), "feat-sparse",
                                  lambda: j().transfer.sparse, lambda v: setattr(j().transfer, "sparse", v))
        lst.add(r)
        activate_rows(lst)
        sec.body.pack_start(lst, False, False, 0)

        # Metadata (#3)
        sec = self._section("metadata", "feat-metadata", _("Keep file details"), "#3")
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, min_children_per_line=2,
                           column_spacing=12, row_spacing=8, homogeneous=True)
        add_classes(grid, "lfc-card")
        for attr, text in (("permissions", _("Permissions")), ("times", _("Modification times")), ("owner", _("Owner")),
                           ("group", _("Group")), ("acls", _("ACLs")), ("xattrs", _("Extended attributes")),
                           ("hardlinks", _("Hard links")), ("devices", _("Devices & specials"))):
            cb = Gtk.CheckButton(label=text)
            cb.set_active(getattr(self.job.metadata, attr))
            cb.connect("toggled", self._on_meta_check, attr)
            self._sync(lambda cb=cb, attr=attr: cb.set_active(getattr(self.job.metadata, attr)))
            grid.add(cb)
        sec.body.pack_start(grid, False, False, 0)
        links = self._bind_combo([(SymlinkPolicy.KEEP.value, _("Copy as links")), (SymlinkPolicy.FOLLOW.value, _("Copy the files they point to")),
                                  (SymlinkPolicy.SKIP.value, _("Leave them out"))],
                                 lambda: j().metadata.symlinks.value, lambda v: setattr(j().metadata, "symlinks", SymlinkPolicy(v)), _("Symbolic links"))
        lst = boxed_list()
        lst.add(row(_("Symbolic links"), _("Drives formatted as FAT or exFAT cannot store links"), "feat-linkdest", [links]))
        sec.body.pack_start(lst, False, False, 0)

        # Filters (#5)
        sec = self._section("filters", "feat-filters", _("Filters"), _("#5 · rules apply top to bottom"))
        self.filter_editor = FilterEditorWidget(self._changed_if_loaded)
        self._sync(lambda: self.filter_editor.set_rules(self.job.filters.rules))
        sec.body.pack_start(self.filter_editor, False, False, 0)
        files = boxed_list()
        self.exclude_from_btn = self._file_button(lambda: j().filters.exclude_from, lambda v: setattr(j().filters, "exclude_from", v))
        files.add(row(_("Exclude list from a file"), _("One pattern per line, like rsync --exclude-from"), "action-import-file", [self.exclude_from_btn]))
        self.files_from_btn = self._file_button(lambda: j().filters.files_from, lambda v: setattr(j().filters, "files_from", v))
        files.add(row(_("Copy only files listed in"), _("Paths relative to the source folder, one per line"), "action-import-file", [self.files_from_btn]))
        sec.body.pack_start(files, False, False, 0)
        test = button("action-test", _("Test filters"), _("See which files the filters keep and skip"))
        test.set_halign(Gtk.Align.START)
        test.connect("clicked", lambda _b: self._test_filters())
        sec.body.pack_start(test, False, False, 0)

        # Speed (#6 #12)
        sec = self._section("speed", "feat-bandwidth", _("Speed"), "#6 #12")
        lst = boxed_list()
        speed = self._bind_spin(lambda: j().performance.speed_limit, lambda v: setattr(j().performance, "speed_limit", v), 1, 100000, name=_("Speed limit"))
        unit = self._bind_combo([(SpeedUnit.MB.value, "MB/s"), (SpeedUnit.KB.value, "KB/s")], lambda: j().performance.speed_unit.value,
                                lambda v: setattr(j().performance, "speed_unit", SpeedUnit(v)), _("Speed unit"))
        limit_sw = switch(j().performance.limit_speed, lambda v: None if self._loading else (setattr(j().performance, "limit_speed", v), self._changed()))
        self._sync(lambda: limit_sw.set_active(j().performance.limit_speed))
        lst.add(row(_("Limit speed"), _("Useful for slow USB sticks that overheat, or to keep a disk free for other work"), "feat-bandwidth",
                    [speed, unit, limit_sw], activatable_widget=limit_sw))
        r, _s = self._bind_switch(_("Run in background priority"), _("Keeps the desktop responsive while copying"), "feat-priority",
                                  lambda: j().performance.low_priority, lambda v: setattr(j().performance, "low_priority", v))
        lst.add(r)
        self.parallel_spin = self._bind_spin(lambda: j().performance.parallel_streams, lambda v: setattr(j().performance, "parallel_streams", int(v)),
                                             1, 16, name=_("Parallel streams"))
        self.parallel_row = row(_("Parallel streams"), _("Helps on NVMe drives and arrays; slows down single USB sticks and hard disks"),
                                "feat-parallel", [self.parallel_spin])
        lst.add(self.parallel_row)
        activate_rows(lst)
        sec.body.pack_start(lst, False, False, 0)

        # Safety (#16 #17)
        sec = self._section("safety", "feat-snapshots", _("Safety"), "#16 #17")
        lst = boxed_list()
        self.atomic_row, self.atomic_switch = self._bind_switch(
            _("Atomic replace"), _("The destination is swapped in one step: never half-updated"), "feat-atomic",
            lambda: j().safety.atomic, lambda v: setattr(j().safety, "atomic", v))
        lst.add(self.atomic_row)
        r, self.snap_switch = self._bind_switch(_("Keep hard-linked snapshots"), _("A dated folder per run; unchanged files take no extra space"),
                                                "feat-snapshots", lambda: j().safety.snapshots, lambda v: setattr(j().safety, "snapshots", v))
        lst.add(r)
        self.link_entry = Gtk.Entry()
        self.link_entry.set_placeholder_text(_("Latest snapshot (automatic)"))
        self.link_entry.set_width_chars(24)
        self.link_entry.get_accessible().set_name(_("Link against"))
        self.link_entry.connect("changed", lambda e: None if self._loading else (setattr(j().safety, "link_dest", e.get_text().strip() or None), self._changed()))
        self._sync(lambda: self.link_entry.set_text(j().safety.link_dest or ""))
        lst.add(row(_("Link against"), _("Leave empty to use the latest snapshot"), "feat-linkdest", [self.link_entry], sub=True))
        daily = self._bind_spin(lambda: j().safety.keep_daily, lambda v: setattr(j().safety, "keep_daily", int(v)), 1, 365, name=_("Daily snapshots to keep"))
        weekly = self._bind_spin(lambda: j().safety.keep_weekly, lambda v: setattr(j().safety, "keep_weekly", int(v)), 0, 520, name=_("Weekly snapshots to keep"))
        lst.add(row(_("Keep"), _("Snapshots from the last 24 hours are always kept"), None,
                    [daily, label(_("daily"), "lfc-dim"), weekly, label(_("weekly"), "lfc-dim")], sub=True))
        activate_rows(lst)
        sec.body.pack_start(lst, False, False, 0)

        # Two-way (#13)
        sec = self._section("twoway", "feat-bidirectional", _("Two-way sync"), "#13")
        self.twoway_note = label(_("Choose Two-way under \"What should happen?\" to use these options."), "lfc-dim", "lfc-small", wrap=True)
        sec.body.pack_start(self.twoway_note, False, False, 0)
        self.twoway_list = lst = boxed_list()
        conflict = self._bind_combo([(ConflictPolicy.NEWER.value, _("Newer file wins")), (ConflictPolicy.LARGER.value, _("Larger file wins")),
                                     (ConflictPolicy.KEEP_BOTH.value, _("Keep both (rename the older one)")),
                                     (ConflictPolicy.SOURCE.value, _("Source always wins")), (ConflictPolicy.ASK.value, _("Ask me (stop and list)"))],
                                    lambda: j().twoway.conflict.value, lambda v: setattr(j().twoway, "conflict", ConflictPolicy(v)), _("When both sides changed"))
        lst.add(row(_("When a file changed on both sides"), None, "policy-conflict", [conflict]))
        r, _s = self._bind_switch(_("Keep deleted and replaced files"), _("They go to .lfc-trash on the same drive instead of being erased"), "feat-trash",
                                  lambda: j().twoway.use_trash, lambda v: setattr(j().twoway, "use_trash", v))
        lst.add(r)
        guard = self._bind_spin(lambda: j().twoway.delete_guard_percent, lambda v: setattr(j().twoway, "delete_guard_percent", int(v)), 1, 100,
                                name=_("Delete guard percent"))
        lst.add(row(_("Stop if more than this share of files would be deleted"), _("Protects against an empty or wrong drive"), "status-warning",
                    [guard, label("%", "lfc-dim")]))
        activate_rows(lst)
        sec.body.pack_start(lst, False, False, 0)

        # Triggers (#14)
        sec = self._section("triggers", "feat-realtime", _("Run automatically"), "#14 #19")
        lst = boxed_list()
        r, _s = self._bind_switch(_("Run when files change"), _("Watches the source folder while LinFileCopy is open or in the tray"), "feat-realtime",
                                  lambda: j().triggers.on_change, lambda v: setattr(j().triggers, "on_change", v))
        lst.add(r)
        debounce = self._bind_spin(lambda: j().triggers.debounce_seconds, lambda v: setattr(j().triggers, "debounce_seconds", v), 1, 600,
                                   name=_("Delay in seconds"))
        lst.add(row(_("Wait for changes to settle"), _("Seconds without changes before the job starts"), None, [debounce, label("s", "lfc-dim")], sub=True))
        r, _s = self._bind_switch(_("Run when the drive is plugged in"), _("For jobs that use a removable drive"), "trigger-drive",
                                  lambda: j().triggers.on_drive_connected, lambda v: setattr(j().triggers, "on_drive_connected", v))
        lst.add(r)
        sched_btn = button("feat-schedule", _("Open Scheduler"), _("Set a time-based schedule"))
        sched_btn.connect("clicked", lambda _b: self._open_scheduler())
        self.schedule_row = row(_("Schedule"), "", "feat-schedule", [sched_btn])
        lst.add(self.schedule_row)
        activate_rows(lst)
        sec.body.pack_start(lst, False, False, 0)

        # Logging (#18)
        sec = self._section("logging", "feat-logging", _("Logging and alerts"), "#18")
        lst = boxed_list()
        lvl = self._bind_combo([(LogLevel.QUIET.value, _("Errors only")), (LogLevel.NORMAL.value, _("Normal")),
                                (LogLevel.VERBOSE.value, _("Detailed")), (LogLevel.DEBUG.value, _("Debug"))],
                               lambda: j().logging.level.value, lambda v: setattr(j().logging, "level", LogLevel(v)), _("Log detail"))
        lst.add(row(_("Log detail"), None, "feat-logging", [lvl]))
        r, _s = self._bind_switch(_("Notify on success"), None, "feat-notify", lambda: j().logging.notify_success,
                                  lambda v: setattr(j().logging, "notify_success", v))
        lst.add(r)
        r, _s = self._bind_switch(_("Notify on failure"), None, "feat-notify", lambda: j().logging.notify_failure,
                                  lambda v: setattr(j().logging, "notify_failure", v))
        lst.add(r)
        retries = self._bind_spin(lambda: j().logging.retries, lambda v: setattr(j().logging, "retries", int(v)), 0, 10, name=_("Retries"))
        delay = self._bind_spin(lambda: j().logging.retry_delay_seconds, lambda v: setattr(j().logging, "retry_delay_seconds", int(v)), 5, 3600,
                                name=_("First retry delay"))
        lst.add(row(_("Retry after I/O errors"), _("The wait doubles after each attempt"), "action-retry",
                    [retries, label(_("times, first after"), "lfc-dim"), delay, label("s", "lfc-dim")]))
        activate_rows(lst)
        sec.body.pack_start(lst, False, False, 0)

    def _file_button(self, get: Callable[[], str | None], set_: Callable[[str | None], None]) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        add_classes(box, "linked")
        pick = Gtk.Button()
        lbl = label(_("None"), ellipsize=True)
        lbl.set_max_width_chars(18)
        pick.add(lbl)
        clear_btn = button("action-close", None, _("Clear"))

        def refresh() -> None:
            value = get()
            lbl.set_text(os.path.basename(value) if value else _("None"))
            pick.set_tooltip_text(value or _("Choose a file"))
            clear_btn.set_sensitive(bool(value))

        def choose(_b: Gtk.Button) -> None:
            dlg = Gtk.FileChooserNative.new(_("Choose a list file"), self.get_toplevel(), Gtk.FileChooserAction.OPEN, _("Choose"), _("Cancel"))
            if dlg.run() == Gtk.ResponseType.ACCEPT:
                set_(dlg.get_filename())
                refresh()
                self._changed()
            dlg.destroy()

        def clear_value(_b: Gtk.Button) -> None:
            set_(None)
            refresh()
            self._changed()

        pick.connect("clicked", choose)
        clear_btn.connect("clicked", clear_value)
        box.pack_start(pick, False, False, 0)
        box.pack_start(clear_btn, False, False, 0)
        self._sync(refresh)
        return box

    def _build_more_popover(self) -> Gtk.Popover:
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(6)
        for icon_id, text, cb in (("action-duplicate", _("Duplicate"), self.duplicate_job),
                                  ("action-export", _("Export to file…"), self.export_job),
                                  ("action-import", _("Import from file…"), self.import_job),
                                  ("action-delete", _("Delete job"), self.delete_job)):
            b = button(icon_id, text)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_child().set_halign(Gtk.Align.START)
            b.connect("clicked", lambda _b, cb=cb: (pop.popdown(), cb()))
            box.pack_start(b, False, False, 0)
        box.show_all()
        pop.add(box)
        return pop

    # =====================================================================
    # job loading
    def _load_initial_job(self) -> None:
        jobs = self.ctx.jobs.list() if self.ctx.jobs else []
        if jobs:
            self.load_job(max(jobs, key=lambda x: x.modified))
        else:
            self.load_job(blank_job(self.ctx.settings.preview_new_jobs), saved=False)
        self._rebuild_job_menu()

    def load_job(self, job: SyncJob, saved: bool = True) -> None:
        """Show ``job`` in the designer (asks about unsaved changes first)."""
        if not self._confirm_discard():
            return
        self._loading = True
        self.job = job
        self.saved_snapshot = job.to_dict() if saved else None
        self.name_entry.set_text(job.name)
        self.src_card.set_endpoint(job.source, job.transfer.copy_contents)
        self.dst_card.set_endpoint(job.destination)
        for fn in self._syncers:
            fn()
        self._loading = False
        self._after_change()
        win = self.ctx.window
        if win is not None and self.ctx.window.nav.current != "designer":
            win.show_page("designer")

    def _confirm_discard(self) -> bool:
        self._commit_paths()
        if not self.dirty or self.ctx.window is None:
            return True
        dlg = Gtk.MessageDialog(transient_for=self.ctx.window, modal=True, message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.NONE, text=_("Save changes to \"{job}\"?").format(job=self.job.name))
        dlg.format_secondary_text(_("Your changes will be lost if you don't save them."))
        dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dlg.add_button(_("Discard"), Gtk.ResponseType.REJECT).get_style_context().add_class("destructive-action")
        dlg.add_button(_("Save"), Gtk.ResponseType.ACCEPT).get_style_context().add_class("suggested-action")
        response = dlg.run()
        dlg.destroy()
        if response == Gtk.ResponseType.ACCEPT:
            self.save_job()
            return True
        return response == Gtk.ResponseType.REJECT

    @property
    def dirty(self) -> bool:
        return self.saved_snapshot is None or self.job.to_dict() != self.saved_snapshot

    def _rebuild_job_menu(self) -> None:
        for child in self.job_popover.get_children():
            self.job_popover.remove(child)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(6)
        new = button("action-new", _("New job"))
        new.set_relief(Gtk.ReliefStyle.NONE)
        new.get_child().set_halign(Gtk.Align.START)
        new.connect("clicked", lambda _b: (self.job_popover.popdown(), self.new_job()))
        box.pack_start(new, False, False, 0)
        jobs = self.ctx.jobs.list() if self.ctx.jobs else []
        if jobs:
            box.pack_start(Gtk.Separator(), False, False, 4)
            box.pack_start(label(_("SAVED JOBS"), "lfc-caption", "lfc-dim"), False, False, 2)
        for jb in jobs:
            b = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            inner.pack_start(label(jb.name), False, False, 0)
            inner.pack_start(label(f"{jb.source.path or '…'} → {jb.destination.path or '…'}", "lfc-dim", "lfc-small", ellipsize=True), False, False, 0)
            inner.set_size_request(320, -1)
            b.add(inner)
            b.connect("clicked", lambda _b, jb=jb: (self.job_popover.popdown(), self.load_job(jb)))
            box.pack_start(b, False, False, 0)
        box.show_all()
        self.job_popover.add(box)

    # =====================================================================
    # change handling
    def _changed_if_loaded(self) -> None:
        if not self._loading:
            self._changed()

    def _changed(self) -> None:
        if self._loading:
            return
        self._after_change()

    def _after_change(self) -> None:
        job = self.job
        self.mode_text.set_text(MODE_TEXT[job.mode])
        if job.mode is Mode.MIRROR:
            self.mirror_warning.show_message(_("Mirror deletes files"), _("Files at the destination that are not in the source will be removed. You will see the list and confirm first."),
                                             "", "status-missing-tool")
        else:
            self.mirror_warning.hide_message()
        self.overwrite_group.set_sensitive(job.mode is not Mode.TWO_WAY)
        removable = any(ep.kind is DriveKind.REMOVABLE for ep in (job.source, job.destination))
        self.eject_row.set_visible(removable or job.drive.eject_after)
        self.inplace_switch.get_parent().get_parent().set_sensitive(not (job.safety.snapshots or job.safety.atomic))
        self.parallel_row.set_sensitive(job.mode is not Mode.TWO_WAY and not (job.safety.snapshots or job.safety.atomic))
        self.atomic_row.set_sensitive(not job.safety.snapshots and job.mode is not Mode.TWO_WAY)
        self.twoway_list.set_sensitive(job.mode is Mode.TWO_WAY)
        self.twoway_note.set_visible(job.mode is not Mode.TWO_WAY)
        self._update_summaries()
        self._update_title()
        self._update_start_label()
        self._schedule_replan()

    def _update_summaries(self) -> None:
        j = self.job
        s = self.sections
        s["drives"].set_summary(", ".join(x for x in (
            _("unlock encrypted") if j.drive.unlock_encrypted else "", _("wait for drive") if j.drive.wait_for_drive else "",
            _("eject after") if j.drive.eject_after else "") if x) or _("Defaults"))
        s["transfer"].set_summary(", ".join(x for x in (
            _("delta") if j.transfer.delta else "", _("in place") if j.transfer.inplace else "",
            _("checksums") if j.transfer.checksum else "", _("size only") if j.transfer.compare is CompareMethod.SIZE_ONLY else "",
            _("resume") if j.transfer.resume else "", _("sparse") if j.transfer.sparse else "") if x))
        md = j.metadata
        kept = [n for n, v in ((_("permissions"), md.permissions), (_("times"), md.times), (_("owner"), md.owner), (_("group"), md.group),
                               (_("ACLs"), md.acls), (_("xattrs"), md.xattrs), (_("hard links"), md.hardlinks)) if v]
        s["metadata"].set_summary(", ".join(kept) or _("Nothing"))
        n_rules = len(j.filters.rules)
        s["filters"].set_summary(_("{n} rules").format(n=n_rules) if n_rules else _("Presets only"))
        s["speed"].set_summary(", ".join(x for x in (
            f"{j.performance.speed_limit:g} {j.performance.speed_unit.value}/s" if j.performance.limit_speed else "",
            _("background priority") if j.performance.low_priority else "",
            _("{n} streams").format(n=j.performance.parallel_streams) if j.performance.parallel_streams > 1 else "") if x) or _("Full speed"))
        s["safety"].set_summary(_("Snapshots: keep {d} daily, {w} weekly").format(d=j.safety.keep_daily, w=j.safety.keep_weekly)
                                if j.safety.snapshots else _("Atomic replace") if j.safety.atomic else _("Off"))
        s["twoway"].set_summary(_("Off") if j.mode is not Mode.TWO_WAY else _("Conflicts: {p}").format(p=j.twoway.conflict.value.replace("_", " ")))
        trig = [x for x in (_("on file change") if j.triggers.on_change else "", _("when drive connected") if j.triggers.on_drive_connected else "",
                            self._schedule_text() if j.schedule.kind is not ScheduleKind.NONE else "") if x]
        s["triggers"].set_summary(", ".join(trig) or _("Manual only"))
        self.schedule_row.subtitle_label.set_text(self._schedule_text())  # type: ignore[attr-defined]
        s["logging"].set_summary(_("{level} · {n} retries").format(level=j.logging.level.value, n=j.logging.retries))

    def _schedule_text(self) -> str:
        from linfilecopy.engine.scheduler import describe_schedule

        return describe_schedule(self.job)

    def _update_title(self) -> None:
        win = self.ctx.window
        if win is not None and win.nav.current == "designer":
            win.title_label.set_text(self.job.name or _("New job"))
            win.refresh_subtitle()

    def subtitle(self) -> str:
        return _("Job Designer · unsaved changes") if self.dirty else _("Job Designer")

    def after_show_all(self) -> None:
        self._set_view(self.view_switch.value)
        self._after_change()

    def on_shown(self) -> None:
        self._update_title()
        self.src_card.refresh_drive_info()
        self.dst_card.refresh_drive_info()

    def _set_view(self, view: str) -> None:
        advanced = view == "advanced"
        for w in self._advanced_widgets:
            w.set_visible(advanced)
        self.basic_meta_row.set_visible(not advanced)

    def _open_section(self, key: str) -> None:
        self.view_switch.set_value("advanced")
        self.sections[key].set_expanded(True)

    # ----- control callbacks -----------------------------------------------------------
    def _on_name(self, entry: Gtk.Entry) -> None:
        if not self._loading:
            self.job.name = entry.get_text()
            self._changed()

    def _on_source_changed(self, card: PathCardWidget) -> None:
        self.job.source = card.endpoint
        self.job.transfer.copy_contents = card.copy_contents
        self._changed()

    def _on_dest_changed(self, card: PathCardWidget) -> None:
        self.job.destination = card.endpoint
        self._changed()

    def _on_swap(self, _b: Gtk.Button) -> None:
        self.job.source, self.job.destination = self.job.destination, self.job.source
        self._loading = True
        self.src_card.set_endpoint(self.job.source, self.job.transfer.copy_contents)
        self.dst_card.set_endpoint(self.job.destination)
        self._loading = False
        self._changed()

    def _on_mode(self, value: str) -> None:
        if not self._loading:
            self.job.mode = Mode(value)
            self._changed()

    def _on_overwrite(self, value: str) -> None:
        if not self._loading:
            self.job.overwrite = OverwritePolicy(value)
            self._changed()

    def _on_preset(self, tb: Gtk.ToggleButton, preset: ExcludePreset) -> None:
        if self._loading:
            return
        presets = [p for p in self.job.filters.presets if p is not preset]
        if tb.get_active():
            presets.append(preset)
        self.job.filters.presets = [p for p in ExcludePreset if p in presets]
        self._changed()

    def _on_meta_check(self, cb: Gtk.CheckButton, attr: str) -> None:
        if not self._loading:
            setattr(self.job.metadata, attr, cb.get_active())
            self._changed()

    def _on_drives(self) -> None:
        self.src_card.refresh_drive_info()
        self.dst_card.refresh_drive_info()
        self._schedule_replan()

    def _request_mount(self, drive: DriveInfo, done: Callable[[], None]) -> None:
        if self.ctx.drives is not None:
            self.ctx.drives.mount(drive, lambda err: done() if not err else info(self.ctx.window, _("Could not mount {drive}").format(drive=drive.label), err, True))

    def _request_unlock(self, drive: DriveInfo, done: Callable[[], None]) -> None:
        from linfilecopy.ui.manager_secrets import PassphraseDialog, store

        value, remember = PassphraseDialog(self.ctx.window, drive).ask()
        if not value or self.ctx.drives is None:
            return
        if remember:
            store(drive.uuid, drive.label, value)

        def finished(err: str | None) -> None:
            if err:
                info(self.ctx.window, _("Could not unlock {drive}").format(drive=drive.label), err, True)
            else:
                done()

        self.ctx.drives.unlock(drive, value, finished)

    # =====================================================================
    # planning
    def _schedule_replan(self) -> None:
        if self._replan_id:
            GLib.source_remove(self._replan_id)
        self._replan_id = GLib.timeout_add(REPLAN_DELAY_MS, self._replan)

    def _replan(self) -> bool:
        self._replan_id = 0
        self._plan_seq += 1
        seq = self._plan_seq
        job = copy.deepcopy(self.job)
        drives = list(self.ctx.drives.drives) if self.ctx.drives else []
        caps = self.ctx.capabilities

        def worker() -> None:
            env = planner.gather_env(job, drives, caps.rsync.path if caps else "rsync",
                                     caps.rsync_version if caps else (3, 2, 7),
                                     caps.ionice.available if caps else True, caps.nice.available if caps else True,
                                     caps.udisks.available if caps else True)
            plan = planner.plan_job(job, env)
            GLib.idle_add(self._show_plan, seq, plan, env)

        threading.Thread(target=worker, name="lfc-plan", daemon=True).start()
        return GLib.SOURCE_REMOVE

    def _show_plan(self, seq: int, plan: Plan, env: planner.PlanEnv) -> bool:
        if seq != self._plan_seq:
            return GLib.SOURCE_REMOVE   # a newer plan is on its way
        self.plan = plan
        caps = self.ctx.capabilities
        engine = f"rsync {caps.rsync.version}" if caps and caps.rsync.version else "rsync"
        if plan.job.mode is Mode.TWO_WAY:
            engine = _("two-way · rsync")
        text = plan.display_text(width=40)
        if plan.job.mode is Mode.TWO_WAY:
            text = "# " + _("Compares both folders, then copies each way with rsync --files-from.") + "\n" + \
                   "# " + _("Deleted and replaced files go to .lfc-trash.") + "\n" + \
                   f"# {plan.source}  ⇄  {plan.destination}"
        self.command.set_plan(text, len(plan.steps), engine)
        fs_notes = [i for i in plan.issues if i.field == "destination.fs" and i.level == INFO]
        if fs_notes:
            self.fs_message.show_message(fs_notes[0].message, fs_notes[0].fix, "info", "misc-info")
        else:
            self.fs_message.hide_message()
        shown = [i for i in plan.issues if i.level != INFO]
        extra = ""
        drive = env.destination.drive
        if drive is not None and drive.free is not None:
            extra = _("{free} free on {drive}").format(free=format_bytes(drive.free), drive=drive.label)
        self.issues.set_issues(shown, extra)
        can_run = caps is None or caps.can_run
        self.start_button.set_sensitive(plan.runnable and can_run)
        self.preview_button.set_sensitive(plan.runnable and can_run)
        return GLib.SOURCE_REMOVE

    def _update_start_label(self) -> None:
        lbl = self.start_button.get_child().get_children()[-1]
        lbl.set_text(_("Start preview") if self.ctx.preview_mode else _("Start"))

    # =====================================================================
    # actions
    def _on_action(self, name: str) -> None:
        win = self.ctx.window
        if name == "new-job":
            self.new_job()
            return
        if win is None or win.nav.current != "designer":
            return
        {"save-job": self.save_job, "start": self.start, "preview": self.preview,
         "copy-command": self.command.copy_to_clipboard, "eject": self._eject_destination}.get(name, lambda: None)()

    def new_job(self) -> None:
        self.load_job(blank_job(self.ctx.settings.preview_new_jobs), saved=False)

    def _new_from_template(self, key: str) -> None:
        tpl = next((t for t in load_templates() if t.key == key), None)
        if tpl is not None:
            job = tpl.instantiate()
            if self.ctx.settings.preview_new_jobs:
                job.preview_first = True
            self.load_job(job, saved=False)

    def save_job(self) -> bool:
        if self.ctx.jobs is None:
            return False
        self._commit_paths()
        # The Scheduler owns the schedule: never overwrite one saved there.
        stored = self.ctx.jobs.get(self.job.id) if self.job.id else None
        if stored is not None:
            self.job.schedule = stored.schedule
        if not self.job.name.strip():
            self.job.name = _("Untitled job")
            self.name_entry.set_text(self.job.name)
        self.ctx.jobs.save(self.job)
        self.saved_snapshot = self.job.to_dict()
        self._update_title()
        self.ctx.publish("jobs-changed")
        self.ctx.publish("schedules-changed")
        return True

    def duplicate_job(self) -> None:
        copy_job = self.job.clone(_("{name} (copy)").format(name=self.job.name))
        self.saved_snapshot = self.job.to_dict()  # the original stays as it was
        self.load_job(copy_job, saved=False)

    def delete_job(self) -> None:
        if self.ctx.jobs is None:
            return
        if not confirm(self.ctx.window, _("Delete \"{job}\"?").format(job=self.job.name),
                       _("The job and its schedule are removed. History and copied files are kept."), _("Delete"), destructive=True):
            return
        from linfilecopy.engine import scheduler

        try:
            scheduler.remove(self.job.id)
        except scheduler.ScheduleError:
            pass
        self.ctx.jobs.delete(self.job.id)
        self.saved_snapshot = self.job.to_dict()   # nothing left to save: don't ask
        self.ctx.publish("jobs-changed")
        self.ctx.publish("schedules-changed")
        self._load_initial_job()

    def export_job(self) -> None:
        dlg = Gtk.FileChooserNative.new(_("Export job"), self.ctx.window, Gtk.FileChooserAction.SAVE, _("Export"), _("Cancel"))
        dlg.set_current_name(f"{self.job.id}.json")
        dlg.set_do_overwrite_confirmation(True)
        if dlg.run() == Gtk.ResponseType.ACCEPT and self.ctx.jobs is not None:
            from pathlib import Path

            self.ctx.jobs.export_job(self.job, Path(dlg.get_filename()))
        dlg.destroy()

    def import_job(self) -> None:
        dlg = Gtk.FileChooserNative.new(_("Import job"), self.ctx.window, Gtk.FileChooserAction.OPEN, _("Import"), _("Cancel"))
        filt = Gtk.FileFilter()
        filt.set_name(_("LinFileCopy jobs"))
        filt.add_pattern("*.json")
        dlg.add_filter(filt)
        if dlg.run() == Gtk.ResponseType.ACCEPT and self.ctx.jobs is not None:
            from pathlib import Path

            try:
                job = self.ctx.jobs.import_job(Path(dlg.get_filename()))
                self.ctx.publish("jobs-changed")
                self.load_job(job)
            except (OSError, ValueError) as exc:
                info(self.ctx.window, _("Could not import the job"), str(exc), True)
        dlg.destroy()

    def _sync_schedule_from_store(self) -> None:
        """Take over a schedule saved in the Scheduler without marking the job changed."""
        stored = self.ctx.jobs.get(self.job.id) if self.ctx.jobs and self.job.id else None
        if stored is None or stored.schedule == self.job.schedule:
            return
        self.job.schedule = stored.schedule
        if self.saved_snapshot is not None:
            self.saved_snapshot["schedule"] = stored.to_dict()["schedule"]
        self._update_summaries()

    def _open_scheduler(self) -> None:
        if self.dirty:
            self.save_job()
        self.ctx.publish("schedule-job", self.job.id)
        self.ctx.window.show_page("scheduler")

    def _eject_destination(self) -> None:
        if self.ctx.drives is None:
            return
        for ep in (self.job.destination, self.job.source):
            drive = next((d for d in self.ctx.drives.drives if ep.volume_uuid and d.uuid == ep.volume_uuid), None)
            if drive is not None and drive.kind is DriveKind.REMOVABLE:
                self.ctx.drives.eject(drive)
                return

    # ----- preview / start ---------------------------------------------------------------------
    def _commit_paths(self) -> None:
        """Apply paths typed into the cards (keyboard shortcuts don't move focus)."""
        self.src_card._commit_entry()
        self.dst_card._commit_entry()

    def _ready_to_run(self) -> bool:
        self._commit_paths()
        if self.dirty:
            self.save_job()
        return self.plan is not None and self.plan.runnable and self.ctx.runs is not None

    def preview(self) -> None:
        if self._ready_to_run():
            launch.open_preview(self.ctx, self.job)

    def start(self) -> None:
        if self._ready_to_run():
            launch.start_interactive(self.ctx, self.job)

    # ----- filter test ---------------------------------------------------------------------------
    def _test_filters(self) -> None:
        source = self.job.source.path
        if not source or not os.path.isdir(source):
            info(self.ctx.window, _("Choose a source folder first"), _("The test lists what the filters keep and skip in the source folder."))
            return
        job = copy.deepcopy(self.job)
        dlg = Gtk.Dialog(title=_("Filter test"), transient_for=self.ctx.window, modal=True)
        dlg.set_default_size(560, 460)
        dlg.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        dlg.connect("response", lambda d, _r: d.destroy())
        area = dlg.get_content_area()
        for side in ("top", "bottom", "start", "end"):
            getattr(area, f"set_margin_{side}")(14)
        area.set_spacing(10)
        summary = label(_("Scanning…"), wrap=True)
        area.pack_start(summary, False, False, 0)
        view = Gtk.TextView(editable=False, monospace=True)
        scroll = Gtk.ScrolledWindow()
        scroll.add(view)
        area.pack_start(scroll, True, True, 0)
        dlg.show_all()

        def worker() -> None:
            matcher = FilterMatcher.for_job(job)
            kept = skipped = 0
            skipped_paths: list[str] = []
            for dirpath, dirnames, filenames in os.walk(source):
                rel_dir = os.path.relpath(dirpath, source)
                rel_dir = "" if rel_dir == "." else rel_dir
                for d in list(dirnames):
                    rel = f"{rel_dir}/{d}" if rel_dir else d
                    if matcher.excluded(rel, True):
                        dirnames.remove(d)
                        skipped += 1
                        if len(skipped_paths) < 300:
                            skipped_paths.append(rel + "/")
                for f in filenames:
                    rel = f"{rel_dir}/{f}" if rel_dir else f
                    if matcher.excluded(rel, False):
                        skipped += 1
                        if len(skipped_paths) < 300:
                            skipped_paths.append(rel)
                    else:
                        kept += 1
                if kept + skipped > 200_000:
                    break
            GLib.idle_add(done, kept, skipped, skipped_paths)

        def done(kept: int, skipped: int, paths: list[str]) -> bool:
            summary.set_text(_("{kept} files are copied. {skipped} files and folders are skipped (a skipped folder hides everything inside it).").format(
                kept=f"{kept:,}", skipped=f"{skipped:,}"))
            view.get_buffer().set_text("\n".join(paths) if paths else _("Nothing is skipped."))
            return GLib.SOURCE_REMOVE

        threading.Thread(target=worker, name="lfc-filter-test", daemon=True).start()
