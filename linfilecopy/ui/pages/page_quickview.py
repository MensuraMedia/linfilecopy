"""Quick View: every job at a glance — source → destination, when it runs, and Run now.

Each job is a card with its route, schedule or trigger, last result and a
"Run now" button. While the job runs, the card shows a live progress bar
(the same run is also shown in Active Transfers). Run now goes through
``manager_launch.start_interactive``, so Preview mode, "Always preview
first" and the Mirror delete confirmation still apply.
"""
from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from linfilecopy.engine import scheduler  # noqa: E402
from linfilecopy.engine.runner import JobRun  # noqa: E402
from linfilecopy.formatting import format_bytes, format_duration  # noqa: E402
from linfilecopy.i18n import _, ngettext  # noqa: E402
from linfilecopy.model.enums import Mode, RunStatus, ScheduleKind  # noqa: E402
from linfilecopy.model.history import RunRecord  # noqa: E402
from linfilecopy.model.job import Endpoint, SyncJob  # noqa: E402
from linfilecopy.ui.components.component_common import add_classes, clear, label  # noqa: E402
from linfilecopy.ui.components.component_dialogs import empty_state  # noqa: E402
from linfilecopy.ui.icons import button, icon, icon_name  # noqa: E402
from linfilecopy.ui.pages.page_base import BasePage  # noqa: E402
from linfilecopy.ui.pages.page_history import when_text  # noqa: E402

MODE_ICON = {Mode.COPY: "mode-copy", Mode.MIRROR: "mode-mirror", Mode.TWO_WAY: "mode-twoway"}
MODE_TEXT = {Mode.COPY: _("Copy"), Mode.MIRROR: _("Mirror"), Mode.TWO_WAY: _("Two-way")}
RESULT_TEXT = {RunStatus.SUCCESS: _("Completed"), RunStatus.WARNING: _("Completed with warnings"),
               RunStatus.FAILED: _("Failed"), RunStatus.CANCELLED: _("Cancelled")}
RESULT_CLASS = {RunStatus.SUCCESS: "lfc-ok", RunStatus.WARNING: "lfc-warn", RunStatus.FAILED: "lfc-err"}


def endpoint_text(ep: Endpoint) -> str:
    """"62 GB Volume › Documents" for drive endpoints, the path otherwise."""
    if ep.volume_label and ep.volume_uuid:
        return f"{ep.volume_label} › {ep.relative_path}" if ep.relative_path else ep.volume_label
    return ep.path or _("(not chosen)")


def when_it_runs(job: SyncJob) -> str:
    parts = []
    if job.schedule.kind is not ScheduleKind.NONE:
        parts.append(scheduler.describe_schedule(job))
    if job.triggers.on_drive_connected:
        parts.append(_("when the drive is plugged in"))
    if job.triggers.on_change:
        parts.append(_("when files change"))
    return " · ".join(parts) if parts else _("Manual only")


class JobCard(Gtk.Box):
    """One job: name, route, when it runs, last result, Run now, live progress."""

    def __init__(self, page: "QuickViewPage", job: SyncJob) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.page = page
        self.job = job
        self.run: JobRun | None = None
        add_classes(self, "lfc-card")
        self.get_accessible().set_name(job.name)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        mode_img = add_classes(icon(MODE_ICON[job.mode]), "lfc-accent")
        mode_img.set_tooltip_text(MODE_TEXT[job.mode])
        top.pack_start(mode_img, False, False, 0)
        top.pack_start(label(job.name, "lfc-group-title", ellipsize=True), True, True, 0)
        self.edit_btn = button("action-edit", None, _("Edit {job}").format(job=job.name), flat=True)
        self.edit_btn.connect("clicked", lambda _b: page.ctx.publish("edit-job", job))
        self.show_btn = button("nav-transfers", _("Show"), _("Open Active Transfers"), flat=True)
        self.show_btn.connect("clicked", lambda _b: page.ctx.window.show_page("transfers"))
        self.run_btn = button("action-start", _("Run now"), _("Run {job} now").format(job=job.name), "suggested-action")
        self.run_btn.connect("clicked", lambda _b: self._run_now())
        for b in (self.edit_btn, self.show_btn, self.run_btn):
            b.set_valign(Gtk.Align.CENTER)
            top.pack_start(b, False, False, 0)
        self.pack_start(top, False, False, 0)

        route = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        route.pack_start(add_classes(icon("ep-source"), "lfc-dim"), False, False, 0)
        src = label(endpoint_text(job.source), ellipsize=True)
        src.set_tooltip_text(job.source.path)
        route.pack_start(src, True, True, 0)
        arrow = add_classes(icon("mode-twoway" if job.mode is Mode.TWO_WAY else "mode-copy"), "lfc-dim")
        route.pack_start(arrow, False, False, 0)
        route.pack_start(add_classes(icon("ep-destination"), "lfc-dim"), False, False, 0)
        dst = label(endpoint_text(job.destination), ellipsize=True)
        dst.set_tooltip_text(job.destination.path)
        route.pack_start(dst, True, True, 0)
        route.set_homogeneous(False)
        self.pack_start(route, False, False, 0)

        info = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        sched_icon = "status-scheduled" if job.schedule.kind is not ScheduleKind.NONE and job.schedule.enabled else "feat-schedule"
        if job.triggers.on_drive_connected:
            sched_icon = "trigger-drive"
        info.pack_start(add_classes(icon(sched_icon), "lfc-dim"), False, False, 0)
        schedule_text = when_it_runs(job)
        nxt = scheduler.next_run(job)
        if nxt is not None:
            schedule_text += " · " + _("next {when}").format(when=nxt.strftime("%a %d %b %H:%M"))
        info.pack_start(label(schedule_text, "lfc-dim", "lfc-small", ellipsize=True), True, True, 0)
        self.last_icon = icon("empty-history")
        self.last_label = label(_("Never run"), "lfc-dim", "lfc-small", xalign=1.0, ellipsize=True)
        info.pack_end(self.last_label, False, False, 0)
        info.pack_end(self.last_icon, False, False, 0)
        self.pack_start(info, False, False, 0)

        self.progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.bar = Gtk.ProgressBar()
        add_classes(self.bar, "lfc-progress")
        self.bar.get_accessible().set_name(_("Progress of {job}").format(job=job.name))
        self.progress_text = label("", "lfc-small", ellipsize=True)
        self.progress_box.pack_start(self.bar, False, False, 0)
        self.progress_box.pack_start(self.progress_text, False, False, 0)
        self.progress_box.set_no_show_all(True)
        self.pack_start(self.progress_box, False, False, 0)

    # ----- state ----------------------------------------------------------------------
    def set_last(self, rec: RunRecord | None) -> None:
        if rec is None:
            self.last_label.set_text(_("Never run"))
            self.last_icon.set_from_icon_name(icon_name("empty-history"), Gtk.IconSize.BUTTON)
            return
        text = RESULT_TEXT.get(rec.status, rec.status.value)
        self.last_label.set_text(_("Last run {when}: {result}").format(when=when_text(rec.started), result=text))
        icon_id = {RunStatus.SUCCESS: "status-success", RunStatus.WARNING: "status-warning",
                   RunStatus.FAILED: "status-failed"}.get(rec.status, "status-cancelled")
        self.last_icon.set_from_icon_name(icon_name(icon_id), Gtk.IconSize.BUTTON)
        ctx = self.last_icon.get_style_context()
        for c in RESULT_CLASS.values():
            ctx.remove_class(c)
        if rec.status in RESULT_CLASS:
            ctx.add_class(RESULT_CLASS[rec.status])

    def update_run(self, run: JobRun) -> None:
        self.run = run
        active = run.active
        s = run.snapshot
        self.run_btn.set_sensitive(not active)
        self.run_btn.get_child().get_children()[-1].set_text(_("Running…") if active else _("Run now"))
        self.show_btn.set_visible(active)
        self.progress_box.set_no_show_all(False)
        self.progress_box.show_all()
        paused = run.status is RunStatus.PAUSED
        bar_ctx = self.bar.get_style_context()
        (bar_ctx.add_class if paused or run.status in (RunStatus.QUEUED, RunStatus.WAITING, RunStatus.CANCELLED)
         else bar_ctx.remove_class)("paused")
        if run.status is RunStatus.SUCCESS:
            self.bar.set_fraction(1.0)
        elif active and s.percent == 0 and s.bytes_done == 0:
            self.bar.pulse()
        else:
            self.bar.set_fraction(s.fraction if s.percent else self.bar.get_fraction())
        text_ctx = self.progress_text.get_style_context()
        for c in RESULT_CLASS.values():
            text_ctx.remove_class(c)
        if run.status is RunStatus.RUNNING:
            eta = format_duration(s.eta_seconds) if s.eta_seconds else "—"
            text = _("{p}% · {done} · {speed}/s · {eta} left").format(
                p=s.percent, done=format_bytes(s.bytes_done), speed=format_bytes(s.speed_bps), eta=eta)
            if run.step_description and run.plan and len(run.plan.steps) > 1:
                text = f"{run.step_description} · {text}"
        elif paused:
            text = _("Paused at {p}%").format(p=s.percent)
        elif run.status in (RunStatus.QUEUED, RunStatus.WAITING):
            text = run.queued_reason or _("Waiting")
        else:
            text = f"{RESULT_TEXT.get(run.status, run.status.value)} · {run.message}"
            if run.status in RESULT_CLASS:
                text_ctx.add_class(RESULT_CLASS[run.status])
        self.progress_text.set_text(text)

    def _run_now(self) -> None:
        from linfilecopy.ui.manager_launch import start_interactive

        fresh = self.page.ctx.jobs.get(self.job.id) if self.page.ctx.jobs else None
        start_interactive(self.page.ctx, fresh or self.job, stay=True)


class QuickViewPage(BasePage):
    page_id = "quickview"
    title = _("Quick View")

    def build_content(self) -> None:
        self.cards: dict[str, JobCard] = {}
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.count = label("", "lfc-dim")
        head.pack_start(self.count, True, True, 0)
        new = button("action-new", _("New job"))
        new.set_action_name("app.new-job")
        head.pack_end(new, False, False, 0)
        self.content.pack_start(head, False, False, 0)
        # One card per row; each card is only as tall as its content.
        self.cards_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.content.pack_start(self.cards_box, False, False, 0)
        self.empty = empty_state("nav-quickview", _("No jobs yet"),
                                 _("Create a job in the Job Designer or from a template. It will appear here with a Run now button."))
        self.empty.set_margin_top(60)
        self.content.pack_start(self.empty, False, False, 0)
        self.ctx.subscribe("jobs-changed", self.reload)
        self.ctx.subscribe("schedules-changed", self.reload)
        self.ctx.subscribe("history-changed", self._refresh_last)
        self.ctx.subscribe("run-updated", self._on_run)
        self.reload()

    def after_show_all(self) -> None:
        self.empty.set_visible(not self.cards)
        for card in self.cards.values():
            if card.run is None:
                card.progress_box.hide()
            card.show_btn.set_visible(bool(card.run and card.run.active))

    def on_shown(self) -> None:
        self._refresh_last()

    def reload(self) -> None:
        jobs = self.ctx.jobs.list() if self.ctx.jobs else []
        runs = {c.job.id: c.run for c in self.cards.values() if c.run is not None}
        clear(self.cards_box)
        self.cards = {}
        for job in jobs:
            card = JobCard(self, job)
            self.cards[job.id] = card
            self.cards_box.pack_start(card, False, False, 0)
        self.cards_box.show_all()
        for job_id, run in runs.items():
            if job_id in self.cards:
                self.cards[job_id].update_run(run)
        for card in self.cards.values():
            if card.run is None:
                card.show_btn.hide()
        active = [r for r in (self.ctx.runs.active() if self.ctx.runs else []) if not r.preview]
        for run in active:
            if run.job.id in self.cards:
                self.cards[run.job.id].update_run(run)
        self.count.set_text(ngettext("{n} job", "{n} jobs", len(jobs)).format(n=len(jobs)))
        self.empty.set_visible(not jobs)
        self._refresh_last()

    def _refresh_last(self, *_args: object) -> None:
        if self.ctx.history is None or not self.cards:
            return
        history, ids = self.ctx.history, list(self.cards)

        def worker() -> None:
            # The last *finished* run: a running one is shown by the progress bar instead.
            last = {job_id: next((r for r in history.list(limit=10, job_id=job_id)
                                  if r.status.finished and not r.dry_run), None) for job_id in ids}
            GLib.idle_add(self._fill_last, last)

        threading.Thread(target=worker, name="lfc-quickview", daemon=True).start()

    def _fill_last(self, last: dict[str, RunRecord | None]) -> bool:
        for job_id, rec in last.items():
            card = self.cards.get(job_id)
            if card is not None:
                card.set_last(rec)
        return GLib.SOURCE_REMOVE

    def _on_run(self, run: JobRun) -> None:
        if run.preview:
            return
        card = self.cards.get(run.job.id)
        if card is not None:
            card.update_run(run)
        if not run.active:
            self._refresh_last()
