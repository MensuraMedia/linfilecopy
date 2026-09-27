"""Dashboard: totals, what is running, recent runs, templates, what is coming up."""
from __future__ import annotations

import datetime as dt
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from linfilecopy.engine import scheduler  # noqa: E402
from linfilecopy.engine.runner import JobRun  # noqa: E402
from linfilecopy.formatting import format_bytes, format_duration  # noqa: E402
from linfilecopy.i18n import _, ngettext  # noqa: E402
from linfilecopy.model.enums import RunStatus, ScheduleKind, Trigger  # noqa: E402
from linfilecopy.model.history import RunRecord  # noqa: E402
from linfilecopy.model.templates import load_templates  # noqa: E402
from linfilecopy.ui.components.component_common import (MessageBar, add_classes, boxed_list, clear, group, label,  # noqa: E402
                                                        row, stat_tile)
from linfilecopy.ui.icons import button, icon, icon_name  # noqa: E402
from linfilecopy.ui.pages.page_base import BasePage  # noqa: E402
from linfilecopy.ui.pages.page_history import STATUS, when_text  # noqa: E402

WEEK = 7 * 86400


class DashboardPage(BasePage):
    page_id = "dashboard"
    title = _("Dashboard")

    def build_content(self) -> None:
        self.tool_banner = MessageBar("err", "status-missing-tool")
        self.content.pack_start(self.tool_banner, False, False, 0)

        tiles = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        t1, self.data_num, _c = stat_tile("stat-data", "—", _("copied in the last 7 days"))
        t2, self.files_num, _c = stat_tile("stat-files", "—", _("files copied in the last 7 days"))
        t3, self.jobs_num, self.jobs_cap = stat_tile("stat-jobs", "—", _("saved jobs"))
        self.fail_tile, self.fail_num, self.fail_cap = stat_tile("status-failed", "0", _("failed runs need attention"), bad=True)
        for i, t in enumerate((t1, t2, t3, self.fail_tile)):
            tiles.attach(t, i, 0, 1, 1)
        self.tiles = tiles
        self.content.pack_start(tiles, False, False, 0)

        cols = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20, homogeneous=False)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.running_list = boxed_list()
        self.running_group = group(_("Running now"), "nav-transfers", None, self.running_list)
        left.pack_start(self.running_group, False, False, 0)
        self.recent_list = boxed_list()
        left.pack_start(group(_("Recent activity"), "nav-history", None, self.recent_list), False, False, 0)
        self.templates_list = boxed_list()
        self.templates_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.templates_list.connect("row-activated", self._on_template)
        right.pack_start(group(_("Start from a template"), "action-templates", None, self.templates_list), False, False, 0)
        self.upcoming_list = boxed_list()
        right.pack_start(group(_("Coming up"), "nav-scheduler", None, self.upcoming_list), False, False, 0)
        cols.pack_start(left, True, True, 0)
        cols.pack_start(right, True, True, 0)
        self.cols = cols
        self.content.pack_start(cols, False, False, 0)
        self._build_templates()
        self._running_rows: dict[str, tuple[Gtk.ListBoxRow, Gtk.ProgressBar, Gtk.Label, Gtk.Button]] = {}

        for topic in ("history-changed", "jobs-changed", "schedules-changed"):
            self.ctx.subscribe(topic, lambda *_a: self.refresh())
        self.ctx.subscribe("capabilities", lambda _c: self._show_tools())
        self.ctx.subscribe("run-updated", self._on_run)
        self.connect("size-allocate", self._on_size)
        self._narrow = False
        self.refresh()
        self._refresh_running()

    def _on_size(self, _w: Gtk.Widget, _a: object) -> None:
        narrow = self.get_allocated_width() < 820
        if narrow != self._narrow:
            self._narrow = narrow
            GLib.idle_add(self._relayout, narrow)

    def _relayout(self, narrow: bool) -> bool:
        self.cols.set_orientation(Gtk.Orientation.VERTICAL if narrow else Gtk.Orientation.HORIZONTAL)
        children = self.tiles.get_children()[::-1]
        for c in children:
            self.tiles.remove(c)
        for i, c in enumerate(children):
            self.tiles.attach(c, i % 2 if narrow else i, i // 2 if narrow else 0, 1, 1)
        return GLib.SOURCE_REMOVE

    def after_show_all(self) -> None:
        self._refresh_running()

    def on_shown(self) -> None:
        self.refresh()

    # ----- data --------------------------------------------------------------------------
    def refresh(self) -> None:
        if self.ctx.history is None or self.ctx.jobs is None:
            return
        history, jobs_store = self.ctx.history, self.ctx.jobs

        def worker() -> None:
            totals = history.totals_since(time.time() - WEEK)
            failures = history.unresolved_failures()
            recent = history.list(limit=6)
            jobs = jobs_store.list()
            GLib.idle_add(self._fill, totals, failures, recent, jobs)

        threading.Thread(target=worker, name="lfc-dashboard", daemon=True).start()

    def _fill(self, totals, failures, recent, jobs) -> bool:  # type: ignore[no-untyped-def]
        self.data_num.set_text(format_bytes(totals.bytes))
        self.files_num.set_text(f"{totals.files:,}")
        scheduled = sum(1 for j in jobs if j.schedule.kind is not ScheduleKind.NONE and j.schedule.enabled)
        self.jobs_num.set_text(str(len(jobs)))
        self.jobs_cap.set_text(ngettext("saved job · {n} scheduled", "saved jobs · {n} scheduled", len(jobs)).format(n=scheduled))
        self.fail_num.set_text(str(len(failures)))
        self.fail_tile.set_opacity(1.0 if failures else 0.55)
        self.fail_cap.set_text(ngettext("failed run needs attention", "failed runs need attention", len(failures))
                               if failures else _("no failed runs"))
        self._fill_recent(recent)
        self._fill_upcoming(jobs)
        return GLib.SOURCE_REMOVE

    def _fill_recent(self, recent: list[RunRecord]) -> None:
        clear(self.recent_list)
        if not recent:
            self.recent_list.add(row(_("No runs yet"), _("Design a job, then press Start."), "empty-history"))
        for rec in recent[:5]:
            icon_id, _t = STATUS.get(rec.status, ("misc-info", ""))
            kind = {"success": "lfc-ok", "failed": "lfc-err", "warning": "lfc-warn"}.get(rec.status.value, "lfc-dim")
            if rec.dry_run:
                icon_id, kind = "status-dryrun", "lfc-accent"
            status_img = add_classes(icon(icon_id), kind)
            if rec.dry_run:
                detail = ngettext("{n} change found", "{n} changes found", rec.stats.get("changes", 0)).format(n=rec.stats.get("changes", 0))
            elif rec.status is RunStatus.FAILED:
                detail = rec.message
            else:
                detail = _("{size}, {files} files in {time}").format(size=format_bytes(rec.bytes), files=f"{rec.files:,}",
                                                                     time=format_duration(rec.duration))
            name = rec.job_name + (" · " + _("preview") if rec.dry_run else "")
            if rec.status is RunStatus.FAILED:
                b = button("action-retry", _("Retry"), None)
            else:
                b = button("action-rerun", _("Run again"), None)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.connect("clicked", self._rerun, rec)
            r = row(name, f"{when_text(rec.started)} · {detail}", None, [b])
            r.get_child().pack_start(status_img, False, False, 0)
            r.get_child().reorder_child(status_img, 0)
            self.recent_list.add(r)
        self.recent_list.show_all()

    def _fill_upcoming(self, jobs) -> None:  # type: ignore[no-untyped-def]
        clear(self.upcoming_list)
        items: list[tuple[float, Gtk.ListBoxRow]] = []
        for job in jobs:
            nxt = scheduler.next_run(job)
            if nxt is not None:
                items.append((nxt.timestamp(), row(job.name, f"{_when_future(nxt)} · {scheduler.describe_schedule(job)}", "status-scheduled")))
            if job.triggers.on_drive_connected:
                drive = job.destination.volume_label or job.source.volume_label or _("its drive")
                items.append((time.time() + 10**9, row(job.name, _("When {drive} is plugged in").format(drive=drive), "trigger-drive")))
            if job.triggers.on_change:
                items.append((time.time() + 10**9 + 1, row(job.name, _("When files change in the source folder"), "feat-realtime")))
        items.sort(key=lambda x: x[0])
        if not items:
            self.upcoming_list.add(row(_("Nothing scheduled"), _("Open the Scheduler to run jobs automatically."), "nav-scheduler"))
        for _ts, r in items[:6]:
            self.upcoming_list.add(r)
        self.upcoming_list.show_all()

    def _build_templates(self) -> None:
        for tpl in load_templates():
            r = row(_(tpl.name), _(tpl.description), tpl.icon, [icon("action-expand")])
            r.set_activatable(True)
            r.template_key = tpl.key  # type: ignore[attr-defined]
            r.set_tooltip_text(_("Create a new job from this template"))
            self.templates_list.add(r)

    def _on_template(self, _lb: Gtk.ListBox, r: Gtk.ListBoxRow) -> None:
        key = getattr(r, "template_key", None)
        if key:
            self.ctx.publish("new-from-template", key)

    def _rerun(self, _b: Gtk.Button, rec: RunRecord) -> None:
        import json

        from linfilecopy.model.job import SyncJob

        if self.ctx.runs is None:
            return
        job = (self.ctx.jobs.get(rec.job_id) if self.ctx.jobs else None) or SyncJob.from_dict(json.loads(rec.job_json))
        self.ctx.runs.start(job, Trigger.RETRY if rec.status is RunStatus.FAILED else Trigger.MANUAL)
        self.ctx.window.show_page("transfers")

    # ----- running ------------------------------------------------------------------------
    def _on_run(self, run: JobRun) -> None:
        if run.preview:
            return
        self._refresh_running()

    def _refresh_running(self) -> None:
        runs = [r for r in (self.ctx.runs.active() if self.ctx.runs else []) if not r.preview]
        ids = {r.id for r in runs}
        for rid in list(self._running_rows):
            if rid not in ids:
                r_, *_rest = self._running_rows.pop(rid)
                self.running_list.remove(r_)
        for run in runs:
            if run.id not in self._running_rows:
                bar = Gtk.ProgressBar()
                add_classes(bar, "lfc-progress")
                sub = label("", "lfc-dim", "lfc-small")
                text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                text.pack_start(label(run.job.name), False, False, 0)
                text.pack_start(bar, False, False, 0)
                text.pack_start(sub, False, False, 0)
                btn = button("action-pause", None, _("Pause"))
                btn.connect("clicked", lambda _b, run=run: run.resume() if run.status is RunStatus.PAUSED else run.pause())
                r = Gtk.ListBoxRow()
                box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                box.pack_start(add_classes(icon("status-running"), "lfc-accent"), False, False, 0)
                box.pack_start(text, True, True, 0)
                btn.set_valign(Gtk.Align.CENTER)
                box.pack_start(btn, False, False, 0)
                r.add(box)
                self.running_list.add(r)
                self._running_rows[run.id] = (r, bar, sub, btn)
            r, bar, sub, btn = self._running_rows[run.id]
            s = run.snapshot
            bar.set_fraction(s.fraction)
            paused = run.status is RunStatus.PAUSED
            (bar.get_style_context().add_class if paused else bar.get_style_context().remove_class)("paused")
            if paused:
                sub.set_text(_("Paused at {p}%").format(p=s.percent))
            elif run.status in (RunStatus.QUEUED, RunStatus.WAITING):
                sub.set_text(run.queued_reason or _("Waiting"))
            else:
                eta = format_duration(s.eta_seconds) if s.eta_seconds else "—"
                sub.set_text(_("{p}% · {speed}/s · {eta} left").format(p=s.percent, speed=format_bytes(s.speed_bps), eta=eta))
            img = btn.get_child().get_children()[0]
            img.set_from_icon_name(icon_name("action-start" if paused else "action-pause"), 1)
            btn.set_tooltip_text(_("Resume") if paused else _("Pause"))
            btn.set_visible(run.status in (RunStatus.RUNNING, RunStatus.PAUSED))
        self.running_list.show_all()
        for rid, (_r, _b, _s, btn) in self._running_rows.items():
            run = self.ctx.runs.get(rid) if self.ctx.runs else None
            btn.set_visible(bool(run and run.status in (RunStatus.RUNNING, RunStatus.PAUSED)))
        self.running_group.set_visible(bool(runs))

    # ----- tools ----------------------------------------------------------------------------
    def _show_tools(self) -> None:
        caps = self.ctx.capabilities
        if caps is None or caps.can_run:
            self.tool_banner.hide_message()
            return
        hints = "\n".join(f"{k}: {v}" for k, v in caps.rsync.install.items())
        self.tool_banner.show_message(_("rsync is required to run jobs"), f"{caps.rsync.missing_effect}\n{hints}", "err", "status-missing-tool")


def _when_future(when: dt.datetime) -> str:
    today = dt.date.today()
    if when.date() == today:
        return _("Today {t}").format(t=when.strftime("%H:%M"))
    if when.date() == today + dt.timedelta(days=1):
        return _("Tomorrow {t}").format(t=when.strftime("%H:%M"))
    if (when.date() - today).days < 7:
        return when.strftime("%a %H:%M")
    return when.strftime("%Y-%m-%d %H:%M")
