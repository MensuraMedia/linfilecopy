"""Scheduler (#19, #14): all schedules and triggers in one place, with the exact unit/cron text."""
from __future__ import annotations

import datetime as dt
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from linfilecopy.engine import scheduler as sc  # noqa: E402
from linfilecopy.i18n import _  # noqa: E402
from linfilecopy.model import cron  # noqa: E402
from linfilecopy.model.enums import ScheduleBackend, ScheduleKind  # noqa: E402
from linfilecopy.model.job import SyncJob  # noqa: E402
from linfilecopy.ui.components.component_common import (MessageBar, Segmented, activate_rows, add_classes, badge,  # noqa: E402
                                                        boxed_list, clear, combo, group, label, row, spin, switch,
                                                        switch_row)
from linfilecopy.ui.components.component_dialogs import empty_state  # noqa: E402
from linfilecopy.ui.icons import button, icon  # noqa: E402
from linfilecopy.ui.pages.page_base import BasePage  # noqa: E402

DAY_LABELS = [_("Mo"), _("Tu"), _("We"), _("Th"), _("Fr"), _("Sa"), _("Su")]
KIND_OPTIONS = [(ScheduleKind.NONE.value, _("Off"), None), (ScheduleKind.ONCE.value, _("Once"), None),
                (ScheduleKind.HOURLY.value, _("Hourly"), None), (ScheduleKind.DAILY.value, _("Daily"), None),
                (ScheduleKind.WEEKLY.value, _("Weekly"), None), (ScheduleKind.CUSTOM.value, _("Custom"), "feat-cron")]


class SchedulerPage(BasePage):
    page_id = "scheduler"
    title = _("Scheduler")

    def build_content(self) -> None:
        self.jobs: list[SyncJob] = []
        self.current: SyncJob | None = None
        self._loading = False
        self.sched: sc.Scheduler | None = None
        cols = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=22)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.list = boxed_list()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.connect("row-selected", self._on_row)
        self.list.get_accessible().set_name(_("Jobs and their schedules"))
        self.list_group = group(_("Schedules and triggers"), "feat-schedule", " ", self.list)
        left.pack_start(self.list_group, False, False, 0)
        left.pack_start(label(_("Drive and folder triggers work while LinFileCopy is open or in the tray. Timed schedules run even when it is closed."),
                              "lfc-dim", "lfc-small", wrap=True), False, False, 0)
        self.empty = empty_state("nav-scheduler", _("No saved jobs"), _("Save a job in the Job Designer, then schedule it here."))
        left.pack_start(self.empty, False, False, 20)
        cols.pack_start(left, True, True, 0)

        self.editor = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        add_classes(self.editor, "lfc-card")
        self.editor.set_size_request(460, -1)
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        head.pack_start(icon("feat-schedule"), False, False, 0)
        self.editor_title = label("", "lfc-group-title", ellipsize=True)
        head.pack_start(self.editor_title, True, True, 0)
        self.enabled = switch(False, self._on_enabled)
        self.enabled.get_accessible().set_name(_("Schedule enabled"))
        head.pack_end(self.enabled, False, False, 0)
        self.editor.pack_start(head, False, False, 0)
        self.kind = Segmented(KIND_OPTIONS, ScheduleKind.NONE.value, self._on_kind)
        self.editor.pack_start(self.kind, False, False, 0)

        self.form = Gtk.Grid(column_spacing=12, row_spacing=10)
        self.time_entry = Gtk.Entry(width_chars=6, max_length=5)
        self.time_entry.set_placeholder_text("03:00")
        self.time_entry.get_accessible().set_name(_("Time (HH:MM)"))
        self.time_entry.connect("changed", lambda e: self._set("time", e.get_text().strip()))
        self.date_entry = Gtk.Entry(width_chars=11, max_length=10)
        self.date_entry.set_placeholder_text(dt.date.today().isoformat())
        self.date_entry.get_accessible().set_name(_("Date (YYYY-MM-DD)"))
        self.date_entry.connect("changed", lambda e: self._set("once_date", e.get_text().strip()))
        self.minute_spin = spin(0, 0, 59, 1, 0, lambda v: self._set("minute", int(v)))
        self.minute_spin.get_accessible().set_name(_("Minute past the hour"))
        self.days = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.day_buttons: list[Gtk.ToggleButton] = []
        for i, name in enumerate(DAY_LABELS):
            b = Gtk.ToggleButton(label=name)
            add_classes(b, "lfc-day")
            b.get_accessible().set_name(dt.date(2024, 1, 1 + i).strftime("%A"))
            b.connect("toggled", self._on_day)
            self.day_buttons.append(b)
            self.days.pack_start(b, False, False, 0)
        self.cron_entry = Gtk.Entry(width_chars=22)
        self.cron_entry.set_placeholder_text("30 2 * * 1-5")
        self.cron_entry.get_style_context().add_class("lfc-mono")
        self.cron_entry.get_accessible().set_name(_("Cron expression"))
        self.cron_entry.set_tooltip_text(_("minute hour day-of-month month day-of-week, e.g. 30 2 * * 1-5 = 02:30 on weekdays"))
        self.cron_entry.connect("changed", lambda e: self._set("cron", e.get_text().strip()))
        self.backend = combo([(ScheduleBackend.AUTO.value, _("Automatic")), (ScheduleBackend.SYSTEMD.value, _("systemd user timer")),
                              (ScheduleBackend.CRON.value, _("cron"))], ScheduleBackend.AUTO.value,
                             lambda v: self._set("backend", ScheduleBackend(v)) if v else None)
        self.backend.get_accessible().set_name(_("Scheduling method"))
        self.form_rows: dict[str, list[Gtk.Widget]] = {}
        for r, (key, title, widget) in enumerate((("date", _("On"), self.date_entry), ("time", _("At"), self.time_entry),
                                                  ("minute", _("Minute"), self.minute_spin), ("days", _("Days"), self.days),
                                                  ("cron", _("Expression"), self.cron_entry), ("backend", _("Using"), self.backend))):
            lbl = label(title, "lfc-dim")
            self.form.attach(lbl, 0, r, 1, 1)
            widget.set_halign(Gtk.Align.START)
            self.form.attach(widget, 1, r, 1, 1)
            self.form_rows[key] = [lbl, widget]
        self.editor.pack_start(self.form, False, False, 0)
        self.next_label = label("", "lfc-small", wrap=True)
        self.editor.pack_start(self.next_label, False, False, 0)

        opts = boxed_list()
        r, self.persistent = switch_row(_("Catch up after the computer was off"), _("Runs at the next start if a time was missed"), None,
                                        True, lambda v: self._set("persistent", v))
        opts.add(r)
        r, self.ac_only = switch_row(_("Only on AC power"), _("systemd timers only"), None, False, lambda v: self._set("ac_power_only", v))
        opts.add(r)
        activate_rows(opts)
        self.editor.pack_start(opts, False, False, 0)
        self.message = MessageBar("err", "status-failed")
        self.editor.pack_start(self.message, False, False, 0)
        self.preview_view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False)
        self.preview_view.set_wrap_mode(Gtk.WrapMode.CHAR)
        add_classes(self.preview_view, "lfc-cmd")
        frame = Gtk.Frame()
        add_classes(frame, "lfc-cmd-frame")
        frame.add(self.preview_view)
        self.editor.pack_start(frame, False, False, 0)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_halign(Gtk.Align.END)
        run_now = button("action-start", _("Run now"))
        run_now.connect("clicked", lambda _b: self._run_now())
        self.save_btn = button("action-save", _("Save schedule"), None, "suggested-action")
        self.save_btn.connect("clicked", lambda _b: self._save())
        actions.pack_start(run_now, False, False, 0)
        actions.pack_start(self.save_btn, False, False, 0)
        self.editor.pack_start(actions, False, False, 0)
        cols.pack_start(self.editor, False, False, 0)
        self.content.pack_start(cols, True, True, 0)
        self.cols = cols
        self.connect("size-allocate", self._on_size)
        self._narrow = False

        self.ctx.subscribe("jobs-changed", self.reload)
        self.ctx.subscribe("schedules-changed", self.reload)
        self.ctx.subscribe("schedule-job", self.select_job)
        self._pending: str | None = None
        threading.Thread(target=self._init_scheduler, daemon=True).start()

    def _on_size(self, _w: Gtk.Widget, _a: object) -> None:
        narrow = self.get_allocated_width() < 900
        if narrow != self._narrow:
            self._narrow = narrow
            GLib.idle_add(lambda: (self.cols.set_orientation(Gtk.Orientation.VERTICAL if narrow else Gtk.Orientation.HORIZONTAL),
                                   self.editor.set_size_request(-1 if narrow else 460, -1), False)[-1])

    def after_show_all(self) -> None:
        self.reload()
        self._refresh_editor()

    def _init_scheduler(self) -> None:
        s = sc.Scheduler()
        GLib.idle_add(self._scheduler_ready, s)

    def _scheduler_ready(self, s: sc.Scheduler) -> bool:
        self.sched = s
        self.reload()
        return GLib.SOURCE_REMOVE

    # ----- list ------------------------------------------------------------------------
    def reload(self) -> None:
        self.jobs = self.ctx.jobs.list() if self.ctx.jobs else []
        installed = self.sched.installed() if self.sched else {}
        keep = self.current.id if self.current else self._pending
        clear(self.list)
        for job in self.jobs:
            kind_icon = "status-scheduled" if job.schedule.kind is not ScheduleKind.NONE else "feat-schedule"
            if job.schedule.kind is ScheduleKind.CUSTOM:
                kind_icon = "feat-cron"
            parts = [sc.describe_schedule(job)]
            nxt = sc.next_run(job)
            if nxt:
                parts.append(_("next: {when}").format(when=nxt.strftime("%a %d %b %H:%M")))
            if job.triggers.on_drive_connected:
                parts.append(_("when {drive} is plugged in").format(drive=job.destination.volume_label or job.source.volume_label or _("the drive")))
            if job.triggers.on_change:
                parts.append(_("when files change"))
            badges = []
            backend = installed.get(job.id)
            if backend is not None:
                badges.append(badge("timer" if backend is ScheduleBackend.SYSTEMD else "cron"))
            elif job.schedule.kind is not ScheduleKind.NONE:
                badges.append(badge(_("not installed"), "warn"))
            if job.triggers.on_drive_connected:
                badges.append(badge(_("drive"), "", "trigger-drive"))
            if job.triggers.on_change:
                badges.append(badge(_("watch"), "", "feat-realtime"))
            r = row(job.name, " · ".join(parts), kind_icon, badges)
            r.job_id = job.id  # type: ignore[attr-defined]
            self.list.add(r)
        self.list.show_all()
        self.empty.set_visible(not self.jobs)
        self.editor.set_visible(bool(self.jobs))
        self.list.set_visible(bool(self.jobs))
        self.list_group.note_label.set_text(_("{n} of {total} jobs").format(  # type: ignore[attr-defined]
            n=sum(1 for j in self.jobs if j.schedule.kind is not ScheduleKind.NONE or j.triggers.on_change or j.triggers.on_drive_connected),
            total=len(self.jobs)))
        if keep:
            self.select_job(keep)
        elif self.jobs:
            self.list.select_row(self.list.get_row_at_index(0))

    def select_job(self, job_id: str) -> None:
        for r in self.list.get_children():
            if getattr(r, "job_id", None) == job_id:
                self.list.select_row(r)
                self._pending = None
                return
        self._pending = job_id

    def _on_row(self, _lb: Gtk.ListBox, r: Gtk.ListBoxRow | None) -> None:
        if r is None:
            return
        job = next((j for j in self.jobs if j.id == getattr(r, "job_id", "")), None)
        if job is not None:
            self._edit(job)

    # ----- editor -----------------------------------------------------------------------
    def _edit(self, job: SyncJob) -> None:
        self._loading = True
        self.current = job
        sch = job.schedule
        self.editor_title.set_text(job.name)
        self.kind.set_value(sch.kind.value, notify=False)
        self.enabled.set_active(sch.enabled)
        self.time_entry.set_text(sch.time)
        self.date_entry.set_text(sch.once_date)
        self.minute_spin.set_value(sch.minute)
        for i, b in enumerate(self.day_buttons):
            b.set_active(i in sch.weekdays)
        self.cron_entry.set_text(sch.cron)
        self.backend.set_active_id(sch.backend.value)
        self.persistent.set_active(sch.persistent)
        self.ac_only.set_active(sch.ac_power_only)
        self._loading = False
        self._refresh_editor()

    def _set(self, attr: str, value: object) -> None:
        if self._loading or self.current is None:
            return
        setattr(self.current.schedule, attr, value)
        self._refresh_editor()

    def _on_kind(self, value: str) -> None:
        if self.current is not None and not self._loading:
            self.current.schedule.kind = ScheduleKind(value)
            if self.current.schedule.kind is not ScheduleKind.NONE:
                self.current.schedule.enabled = True
                self._loading = True
                self.enabled.set_active(True)
                self._loading = False
            if self.current.schedule.kind is ScheduleKind.ONCE and not self.current.schedule.once_date:
                self.current.schedule.once_date = (dt.date.today() + dt.timedelta(days=1)).isoformat()
                self._loading = True
                self.date_entry.set_text(self.current.schedule.once_date)
                self._loading = False
        self._refresh_editor()

    def _on_enabled(self, value: bool) -> None:
        self._set("enabled", value)

    def _on_day(self, _b: Gtk.ToggleButton) -> None:
        self._set("weekdays", [i for i, b in enumerate(self.day_buttons) if b.get_active()])

    def _refresh_editor(self) -> None:
        job = self.current
        if job is None:
            return
        kind = job.schedule.kind
        visible = {
            ScheduleKind.NONE: set(), ScheduleKind.ONCE: {"date", "time", "backend"},
            ScheduleKind.HOURLY: {"minute", "backend"}, ScheduleKind.DAILY: {"time", "backend"},
            ScheduleKind.WEEKLY: {"time", "days", "backend"}, ScheduleKind.CUSTOM: {"cron", "backend"},
        }[kind]
        for key, widgets in self.form_rows.items():
            for w in widgets:
                w.set_visible(key in visible)
        self.enabled.set_sensitive(kind is not ScheduleKind.NONE)
        from linfilecopy.model.validation import validate_job

        errors = [i for i in validate_job(job) if i.field.startswith("schedule") and i.blocking]
        if errors:
            self.message.show_message(errors[0].message, errors[0].fix, "err", "status-failed")
        else:
            self.message.hide_message()
        self.save_btn.set_sensitive(not errors)
        nxt = sc.next_run(job)
        self.next_label.set_text(_("Next run: {when}").format(when=nxt.strftime("%A %d %B %Y, %H:%M")) if nxt
                                 else (_("Paused") if kind is not ScheduleKind.NONE and not job.schedule.enabled
                                       else _("No timed schedule.") if kind is ScheduleKind.NONE else ""))
        self.preview_view.get_buffer().set_text(self._unit_preview(job) if not errors else "")

    def _unit_preview(self, job: SyncJob) -> str:
        if job.schedule.kind is ScheduleKind.NONE or self.sched is None:
            return _("# Nothing is installed for this job.")
        try:
            backend = self.sched.backend_for(job)
        except sc.ScheduleError as exc:
            return f"# {exc}"
        if backend is ScheduleBackend.SYSTEMD:
            service, timer = self.sched.unit_texts(job)
            return (f"# ~/.config/systemd/user/{sc.UNIT_PREFIX}{job.id}.timer\n{timer}\n"
                    f"# ~/.config/systemd/user/{sc.UNIT_PREFIX}{job.id}.service\n{service}").rstrip()
        return "# crontab -e\n" + self.sched.cron_block(job)

    def _save(self) -> None:
        job = self.current
        if job is None or self.sched is None or self.ctx.jobs is None:
            return
        try:
            if job.schedule.kind is ScheduleKind.CUSTOM:
                cron.parse(job.schedule.cron)
            backend = self.sched.apply(job)
        except (sc.ScheduleError, cron.CronError) as exc:
            self.message.show_message(_("The schedule could not be saved"), str(exc), "err", "status-failed")
            return
        self.ctx.jobs.save(job)
        self.message.show_message(_("Schedule saved"), _("Installed as a {how}.").format(
            how=_("systemd user timer") if backend is ScheduleBackend.SYSTEMD else _("cron entry")) if backend else _("The schedule was removed."),
            "ok", "status-success")
        self.ctx.publish("jobs-changed")
        self.ctx.publish("schedules-changed")

    def _run_now(self) -> None:
        if self.current is not None and self.ctx.runs is not None:
            from linfilecopy.model.enums import Trigger

            self.ctx.runs.start(self.ctx.jobs.get(self.current.id) or self.current, Trigger.MANUAL)
            self.ctx.window.show_page("transfers")
