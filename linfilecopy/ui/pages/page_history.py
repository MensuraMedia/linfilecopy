"""History & Logs: every run, its result, statistics, log and one-click re-run (B8, #11, #18)."""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from linfilecopy.formatting import format_bytes, format_duration  # noqa: E402
from linfilecopy.i18n import _  # noqa: E402
from linfilecopy.model.enums import RunStatus, Trigger  # noqa: E402
from linfilecopy.model.history import RunRecord  # noqa: E402
from linfilecopy.model.job import SyncJob  # noqa: E402
from linfilecopy.ui.components.component_common import MessageBar, add_classes, clear, combo, label  # noqa: E402
from linfilecopy.ui.components.component_dialogs import empty_state  # noqa: E402
from linfilecopy.ui.icons import button, coloured_pixbuf, icon  # noqa: E402
from linfilecopy.ui.pages.page_base import BasePage  # noqa: E402

STATUS = {
    RunStatus.SUCCESS: ("status-success", _("Completed")),
    RunStatus.WARNING: ("status-warning", _("Warnings")),
    RunStatus.FAILED: ("status-failed", _("Failed")),
    RunStatus.CANCELLED: ("status-cancelled", _("Cancelled")),
    RunStatus.RUNNING: ("status-running", _("Running")),
    RunStatus.PAUSED: ("status-paused", _("Paused")),
    RunStatus.QUEUED: ("status-queued", _("Queued")),
    RunStatus.WAITING: ("status-drive-missing", _("Waiting")),
}
STATUS_COLOUR = {RunStatus.SUCCESS: "lfc_ok", RunStatus.WARNING: "lfc_warn", RunStatus.FAILED: "lfc_err",
                 RunStatus.RUNNING: "lfc_accent", RunStatus.PAUSED: "lfc_dim", RunStatus.CANCELLED: "lfc_dim",
                 RunStatus.QUEUED: "lfc_dim", RunStatus.WAITING: "lfc_warn"}
TRIGGER_TEXT = {Trigger.MANUAL: _("you"), Trigger.SCHEDULE: _("schedule"), Trigger.FILE_CHANGE: _("file change"),
                Trigger.DRIVE_CONNECTED: _("drive connected"), Trigger.RETRY: _("retry")}
LOG_TAIL_LINES = 40


def when_text(ts: float) -> str:
    d = dt.datetime.fromtimestamp(ts)
    today = dt.date.today()
    if d.date() == today:
        return _("Today {t}").format(t=d.strftime("%H:%M"))
    if d.date() == today - dt.timedelta(days=1):
        return _("Yesterday {t}").format(t=d.strftime("%H:%M"))
    if (today - d.date()).days < 7:
        return d.strftime("%a %H:%M")
    return d.strftime("%Y-%m-%d %H:%M")


class HistoryPage(BasePage):
    page_id = "history"
    title = _("History & Logs")

    def build_content(self) -> None:
        self.records: dict[str, RunRecord] = {}
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text(_("Search jobs, commands, errors"))
        self.search.set_width_chars(30)
        self.search.connect("search-changed", lambda _e: self.reload())
        bar.pack_start(self.search, False, False, 0)
        self.status_filter = combo([("all", _("All results")), ("failed", _("Failed only")), ("success", _("Completed")),
                                    ("preview", _("Previews"))], "all", lambda _v: self.reload())
        self.status_filter.get_accessible().set_name(_("Result filter"))
        bar.pack_start(self.status_filter, False, False, 0)
        self.range_filter = combo([("7", _("Last 7 days")), ("30", _("Last 30 days")), ("365", _("Last year")), ("all", _("Everything"))],
                                  "30", lambda _v: self.reload())
        self.range_filter.get_accessible().set_name(_("Date range"))
        bar.pack_start(self.range_filter, False, False, 0)
        self.content.pack_start(bar, False, False, 0)

        # status icon, job, started, duration, copied, files, result, run id, sort key
        self.store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str, str, str, str, str, str, float)
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.get_accessible().set_name(_("Runs"))
        self.tree.set_search_column(1)
        pix = Gtk.CellRendererPixbuf()
        c = Gtk.TreeViewColumn("", pix, pixbuf=0)
        self.tree.append_column(c)
        for i, (title, xalign, expand) in enumerate([(_("Job"), 0.0, True), (_("Started"), 0.0, False), (_("Duration"), 1.0, False),
                                                     (_("Copied"), 1.0, False), (_("Files"), 1.0, False), (_("Result"), 0.0, False)], start=1):
            r = Gtk.CellRendererText(xalign=xalign)
            if i == 1:
                r.props.weight = 700
                r.props.ellipsize = 3
            col = Gtk.TreeViewColumn(title, r, text=i)
            col.set_expand(expand)
            col.set_resizable(True)
            if i == 2:
                col.set_sort_column_id(8)
            self.tree.append_column(col)
        self.tree.get_selection().connect("changed", self._on_selected)
        self.tree.connect("row-activated", lambda *_a: self._rerun())
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(220)
        scroll.set_max_content_height(360)
        scroll.set_propagate_natural_height(True)
        scroll.add(self.tree)
        frame = Gtk.Frame()
        add_classes(frame, "lfc-card")
        frame.add(scroll)
        self.content.pack_start(frame, False, False, 0)
        self.empty = empty_state("empty-history", _("No runs yet"), _("Runs appear here with their results, statistics and logs."))
        self.content.pack_start(self.empty, False, False, 30)

        # details
        self.details = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.message = MessageBar("err", "status-failed")
        left.pack_start(self.message, False, False, 0)
        self.log_view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False)
        self.log_view.set_wrap_mode(Gtk.WrapMode.CHAR)
        add_classes(self.log_view, "lfc-cmd")
        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_min_content_height(200)
        log_scroll.add(self.log_view)
        log_frame = Gtk.Frame()
        add_classes(log_frame, "lfc-cmd-frame")
        log_frame.add(log_scroll)
        left.pack_start(log_frame, True, True, 0)
        self.details.pack_start(left, True, True, 0)

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        add_classes(panel, "lfc-card")
        panel.set_size_request(340, -1)
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        head.pack_start(icon("feat-stats"), False, False, 0)
        head.pack_start(label(_("Run statistics"), "lfc-group-title"), False, False, 0)
        panel.pack_start(head, False, False, 0)
        self.stats_grid = Gtk.Grid(column_spacing=14, row_spacing=4)
        panel.pack_start(self.stats_grid, False, False, 0)
        acts = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=6, row_spacing=6, max_children_per_line=2)
        self.retry_btn = button("action-retry", _("Retry"), _("Run this job again"), "suggested-action")
        self.retry_btn.connect("clicked", lambda _b: self._rerun())
        log_btn = button("action-open-log", _("Open full log"))
        log_btn.connect("clicked", lambda _b: self._open_log())
        cmd_btn = button("action-copy-command", _("Copy command"))
        cmd_btn.connect("clicked", lambda _b: self._copy_command())
        edit_btn = button("action-edit", _("Edit job"))
        edit_btn.connect("clicked", lambda _b: self._edit_job())
        for b in (self.retry_btn, log_btn, cmd_btn, edit_btn):
            acts.add(b)
        panel.pack_start(acts, False, False, 0)
        self.details.pack_start(panel, False, False, 0)
        self.content.pack_start(self.details, True, True, 0)
        self.details.set_no_show_all(True)

        self.ctx.subscribe("history-changed", self.reload)
        self.ctx.subscribe("settings-changed", lambda _s: self.reload())   # recolour after a theme change
        self.ctx.subscribe("select-run", self.select_run)
        self._pending_select: str | None = None
        self.reload()

    # ----- data -------------------------------------------------------------------------
    def after_show_all(self) -> None:
        if self._selected() is None:
            self.details.hide()
        self.empty.set_visible(not self.records)

    def on_shown(self) -> None:
        self.reload()

    def reload(self) -> None:
        if self.ctx.history is None:
            return
        f = self.status_filter.get_active_id()
        statuses = {"failed": [RunStatus.FAILED], "success": [RunStatus.SUCCESS, RunStatus.WARNING]}.get(f)
        days = self.range_filter.get_active_id()
        since = None if days == "all" else time.time() - int(days) * 86400
        query = self.search.get_text().strip()
        history = self.ctx.history

        def worker() -> None:
            recs = history.list(limit=500, search=query, statuses=statuses, since=since)
            if f == "preview":
                recs = [r for r in recs if r.dry_run]
            GLib.idle_add(self._fill, recs)

        threading.Thread(target=worker, name="lfc-history", daemon=True).start()

    def _fill(self, recs: list[RunRecord]) -> bool:
        selected = self._selected_id() or self._pending_select
        self.store.clear()
        self.records = {r.id: r for r in recs}
        for r in recs:
            icon_id, text = STATUS.get(r.status, ("misc-info", r.status.value))
            if r.dry_run:
                icon_id, text = "status-dryrun", _("Preview")
            elif r.status is RunStatus.FAILED and r.exit_code not in (None, 0):
                text = _("Code {n}").format(n=r.exit_code)
            elif r.status is RunStatus.WARNING and r.exit_code:
                text = _("Code {n}").format(n=r.exit_code)
            copied = "—" if r.dry_run else format_bytes(r.bytes)
            files = f"{r.stats.get('changes', 0):,} " + _("changes") if r.dry_run else f"{r.files:,}"
            colour = STATUS_COLOUR.get(r.status, "lfc_dim") if not r.dry_run else "lfc_accent"
            self.store.append([coloured_pixbuf(icon_id, colour, self.tree), r.job_name, when_text(r.started), format_duration(r.duration),
                               copied, files, text, r.id, r.started])
        self.empty.set_visible(not recs)
        if selected:
            self.select_run(selected)
        elif recs:
            self.tree.get_selection().select_path(Gtk.TreePath.new_first())
        else:
            self.details.hide()
        return GLib.SOURCE_REMOVE

    def select_run(self, run_id: str) -> None:
        for row in self.store:
            if row[7] == run_id:
                self.tree.get_selection().select_iter(row.iter)
                self.tree.scroll_to_cell(row.path, None, False, 0, 0)
                self._pending_select = None
                return
        self._pending_select = run_id

    def _selected_id(self) -> str | None:
        model, it = self.tree.get_selection().get_selected()
        return model[it][7] if it is not None else None

    def _selected(self) -> RunRecord | None:
        rid = self._selected_id()
        return self.records.get(rid) if rid else None

    # ----- details -----------------------------------------------------------------------
    def _on_selected(self, _sel: Gtk.TreeSelection) -> None:
        rec = self._selected()
        if rec is None:
            self.details.hide()
            return
        self.details.set_no_show_all(False)
        self.details.show_all()
        if rec.status is RunStatus.FAILED:
            self.message.show_message(rec.message or _("The run failed."), rec.fix, "err", "status-failed")
        elif rec.status is RunStatus.WARNING:
            self.message.show_message(rec.message, rec.fix, "", "status-warning")
        elif rec.status is RunStatus.SUCCESS:
            self.message.show_message(rec.message or _("Completed"), "", "ok", "status-success")
        else:
            self.message.hide_message()
        self.retry_btn.get_child().get_children()[-1].set_text(_("Retry") if rec.status is RunStatus.FAILED else _("Run again"))
        clear(self.stats_grid)
        st = rec.stats or {}
        rows = [
            (_("Started"), dt.datetime.fromtimestamp(rec.started).strftime("%Y-%m-%d %H:%M:%S")),
            (_("Duration"), format_duration(rec.duration)),
            (_("Files checked"), f"{st.get('files', rec.files_total):,}"),
            (_("Files copied"), f"{rec.files:,}" + (_(" ({n} failed)").format(n=rec.files_failed) if rec.files_failed else "")),
            (_("Data copied"), format_bytes(rec.bytes)),
            (_("Deleted"), f"{st.get('deleted', 0):,}"),
            (_("Average speed"), f"{format_bytes(rec.avg_speed)}/s" if rec.bytes else "—"),
            (_("Exit code"), str(rec.exit_code) if rec.exit_code is not None else "—"),
            (_("Started by"), TRIGGER_TEXT.get(rec.trigger, rec.trigger.value)),
        ]
        if rec.dry_run:
            rows.insert(2, (_("Kind"), _("Preview (nothing changed)")))
        for i, (k, v) in enumerate(rows):
            self.stats_grid.attach(label(k, "lfc-dim", "lfc-small"), 0, i, 1, 1)
            self.stats_grid.attach(label(v, selectable=True), 1, i, 1, 1)
        self.stats_grid.show_all()
        self._load_log_tail(rec)

    def _load_log_tail(self, rec: RunRecord) -> None:
        path = rec.log_path

        def worker() -> None:
            text = _("The log file is no longer available.")
            if path and os.path.exists(path):
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        lines = fh.readlines()
                    text = "".join(lines[-LOG_TAIL_LINES:]).rstrip()
                except OSError as exc:
                    text = str(exc)
            GLib.idle_add(self.log_view.get_buffer().set_text, text)

        threading.Thread(target=worker, name="lfc-log-tail", daemon=True).start()

    # ----- actions -------------------------------------------------------------------------
    def _job_for(self, rec: RunRecord) -> SyncJob:
        job = self.ctx.jobs.get(rec.job_id) if self.ctx.jobs else None
        return job or SyncJob.from_dict(json.loads(rec.job_json or "{}"))

    def _rerun(self) -> None:
        rec = self._selected()
        if rec is None or self.ctx.runs is None:
            return
        from linfilecopy.ui.manager_launch import start_interactive

        trigger = Trigger.RETRY if rec.status is RunStatus.FAILED else Trigger.MANUAL
        start_interactive(self.ctx, self._job_for(rec), trigger)

    def _open_log(self) -> None:
        rec = self._selected()
        if rec is not None and rec.log_path and os.path.exists(rec.log_path):
            try:
                Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(rec.log_path).get_uri(), None)
            except GLib.Error:
                pass

    def _copy_command(self) -> None:
        rec = self._selected()
        if rec is not None:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(rec.command, -1)

    def _edit_job(self) -> None:
        rec = self._selected()
        if rec is not None:
            self.ctx.publish("edit-job", self._job_for(rec))
