"""Live card for one run (B3, B4, #11): progress, speed graph, metrics, log, controls."""
from __future__ import annotations

import time
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from linfilecopy.engine.runner import JobRun  # noqa: E402
from linfilecopy.formatting import format_bytes, format_duration  # noqa: E402
from linfilecopy.i18n import _  # noqa: E402
from linfilecopy.model.enums import Mode, RunStatus  # noqa: E402
from linfilecopy.ui.components.component_common import add_classes, badge, label, set_badge  # noqa: E402
from linfilecopy.ui.icons import button, icon, icon_name  # noqa: E402

STATUS_LOOK: dict[RunStatus, tuple[str, str, str]] = {
    RunStatus.QUEUED: ("status-queued", "", _("Queued")),
    RunStatus.WAITING: ("status-drive-missing", "warn", _("Waiting")),
    RunStatus.RUNNING: ("status-running", "info", _("Running")),
    RunStatus.PAUSED: ("status-paused", "", _("Paused")),
    RunStatus.SUCCESS: ("status-success", "ok", _("Completed")),
    RunStatus.WARNING: ("status-warning", "warn", _("Completed with warnings")),
    RunStatus.FAILED: ("status-failed", "err", _("Failed")),
    RunStatus.CANCELLED: ("status-cancelled", "", _("Cancelled")),
}
MODE_ICON = {Mode.COPY: "mode-copy", Mode.MIRROR: "mode-mirror", Mode.TWO_WAY: "mode-twoway"}


class Sparkline(Gtk.DrawingArea):
    """Speed over the last 60 samples: area fill, faint grid, emphasised end point."""

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(-1, 44)
        self.values: list[float] = []
        self.connect("draw", self._draw)
        self.get_accessible().set_name(_("Speed over the last minute"))

    def set_values(self, values: list[float]) -> None:
        self.values = list(values[-60:])
        self.queue_draw()

    def _draw(self, widget: Gtk.Widget, cr) -> bool:  # type: ignore[no-untyped-def]
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        ctx = widget.get_style_context()
        ok, accent = ctx.lookup_color("lfc_accent")
        okb, border = ctx.lookup_color("lfc_border")
        if okb:
            cr.set_source_rgba(border.red, border.green, border.blue, 1)
            cr.set_line_width(1)
            for frac in (0.33, 0.66):
                cr.move_to(0, int(h * frac) + 0.5)
                cr.line_to(w, int(h * frac) + 0.5)
            cr.stroke()
        vals = self.values
        if len(vals) < 2 or not ok:
            return False
        top = max(vals) * 1.15 or 1
        step = w / (60 - 1)
        start_x = w - step * (len(vals) - 1)
        pts = [(start_x + i * step, h - 3 - (v / top) * (h - 6)) for i, v in enumerate(vals)]
        cr.move_to(pts[0][0], h)
        for x, y in pts:
            cr.line_to(x, y)
        cr.line_to(pts[-1][0], h)
        cr.close_path()
        cr.set_source_rgba(accent.red, accent.green, accent.blue, 0.15)
        cr.fill()
        cr.move_to(*pts[0])
        for x, y in pts[1:]:
            cr.line_to(x, y)
        cr.set_source_rgba(accent.red, accent.green, accent.blue, 1)
        cr.set_line_width(1.6)
        cr.stroke()
        cr.arc(pts[-1][0] - 2, pts[-1][1], 3, 0, 6.2832)
        cr.fill()
        return False


class RunCardWidget(Gtk.Box):
    """One card; call :meth:`update` whenever the run changes."""

    def __init__(self, run: JobRun, on_dismiss: Callable[["RunCardWidget"], None], on_retry: Callable[[JobRun], None],
                 on_start_now: Callable[[JobRun], None], on_unlock: Callable[[JobRun], None] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.run = run
        self.on_dismiss = on_dismiss
        add_classes(self, "lfc-card")
        self.set_can_focus(True)
        self.get_accessible().set_name(run.job.name)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.status_icon = icon("status-running")
        top.pack_start(self.status_icon, False, False, 0)
        name = label(run.job.name, "lfc-group-title", ellipsize=True)
        top.pack_start(name, False, False, 0)
        self.badge = badge(_("Running"), "info")
        top.pack_start(self.badge, False, False, 0)
        if run.preview or run.dry_run:
            top.pack_start(badge(_("Preview"), "info", "status-dryrun"), False, False, 0)
        if run.job.drive.eject_after:
            top.pack_start(badge(_("Ejects when done"), "", "action-eject"), False, False, 0)

        self.buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.pause_btn = button("action-pause", _("Pause"), _("Pause (Space)"))
        self.pause_btn.connect("clicked", lambda _b: self.toggle_pause())
        self.cancel_btn = button("action-cancel", _("Cancel"), _("Cancel (Escape)"))
        self.cancel_btn.connect("clicked", lambda _b: self.ask_cancel())
        self.start_now_btn = button("action-start", _("Start now"), _("Start without waiting"))
        self.start_now_btn.connect("clicked", lambda _b: on_start_now(run))
        self.unlock_btn = button("ep-unlock", _("Unlock…"))
        if on_unlock:
            self.unlock_btn.connect("clicked", lambda _b: on_unlock(run))
        self.retry_btn = button("action-retry", _("Retry"), None, "suggested-action")
        self.retry_btn.connect("clicked", lambda _b: on_retry(run))
        self.dismiss_btn = button("action-close", None, _("Dismiss"))
        self.dismiss_btn.connect("clicked", lambda _b: on_dismiss(self))
        for b in (self.start_now_btn, self.unlock_btn, self.pause_btn, self.cancel_btn, self.retry_btn, self.dismiss_btn):
            self.buttons.pack_start(b, False, False, 0)
        top.pack_end(self.buttons, False, False, 0)
        self.pack_start(top, False, False, 0)

        route = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        route.pack_start(add_classes(icon("ep-source"), "lfc-dim"), False, False, 0)
        route.pack_start(label(run.job.source.path, "lfc-dim", "lfc-small", ellipsize=True), False, True, 0)
        route.pack_start(add_classes(icon(MODE_ICON[run.job.mode]), "lfc-dim"), False, False, 0)
        dst = run.job.destination
        route.pack_start(label((f"{dst.volume_label} › {dst.relative_path}" if dst.volume_label and dst.relative_path else dst.path),
                               "lfc-dim", "lfc-small", ellipsize=True), False, True, 0)
        self.pack_start(route, False, False, 0)

        self.bar = Gtk.ProgressBar()
        add_classes(self.bar, "lfc-progress")
        self.pack_start(self.bar, False, False, 0)

        metrics = Gtk.Grid(column_spacing=18, row_spacing=2, column_homogeneous=True)
        self.metric_values: dict[str, Gtk.Label] = {}
        self.metric_names: dict[str, Gtk.Label] = {}
        for col, (key, title) in enumerate((("copied", _("Copied")), ("speed", _("Speed")), ("eta", _("Time left")), ("files", _("Files")))):
            n = label(title, "lfc-dim", "lfc-small")
            v = label("—", "lfc-metric-value")
            metrics.attach(n, col, 0, 1, 1)
            metrics.attach(v, col, 1, 1, 1)
            self.metric_values[key], self.metric_names[key] = v, n
        self.pack_start(metrics, False, False, 0)
        self.spark = Sparkline()
        self.pack_start(self.spark, False, False, 0)
        cur = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        cur.pack_start(add_classes(icon("ep-folder"), "lfc-dim"), False, False, 0)
        self.current = label("", "lfc-mono", "lfc-dim", ellipsize=True)
        cur.pack_start(self.current, True, True, 0)
        self.pack_start(cur, False, False, 0)
        self.note = label("", "lfc-small", wrap=True)
        self.pack_start(self.note, False, False, 0)

        self.log_expander = Gtk.Expander(label=_("Live log"))
        self.log_view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False)
        self.log_view.set_wrap_mode(Gtk.WrapMode.CHAR)
        add_classes(self.log_view, "lfc-cmd")
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(140)
        scroll.add(self.log_view)
        self.log_expander.add(scroll)
        self.pack_start(self.log_expander, False, False, 0)
        self._log_count = 0
        self.show_all()
        self.update()

    # ----- controls -----------------------------------------------------------------
    def toggle_pause(self) -> None:
        if self.run.status is RunStatus.RUNNING:
            self.run.pause()
        elif self.run.status is RunStatus.PAUSED:
            self.run.resume()
        self.update()

    def ask_cancel(self) -> None:
        from linfilecopy.ui.components.component_dialogs import confirm

        if not self.run.active:
            return
        if self.run.status is RunStatus.QUEUED or confirm(
                self.get_toplevel(), _("Cancel \"{job}\"?").format(job=self.run.job.name),
                _("Files copied so far stay at the destination. Partly copied files can be resumed next time."),
                _("Cancel run"), destructive=True):
            self.run.cancel()

    # ----- refresh ---------------------------------------------------------------------
    def update(self) -> None:
        run = self.run
        s = run.snapshot
        icon_id, kind, text = STATUS_LOOK[run.status]
        self.status_icon.set_from_icon_name(icon_name(icon_id), 1)
        ctx = self.status_icon.get_style_context()
        for c in ("lfc-ok", "lfc-err", "lfc-warn", "lfc-accent", "lfc-dim"):
            ctx.remove_class(c)
        ctx.add_class({"ok": "lfc-ok", "err": "lfc-err", "warn": "lfc-warn", "info": "lfc-accent"}.get(kind, "lfc-dim"))
        set_badge(self.badge, text, kind)
        active = run.active
        self.pause_btn.set_visible(run.status in (RunStatus.RUNNING, RunStatus.PAUSED))
        paused = run.status is RunStatus.PAUSED
        pause_label = self.pause_btn.get_child().get_children()
        pause_label[0].set_from_icon_name(icon_name("action-start" if paused else "action-pause"), 1)
        pause_label[-1].set_text(_("Resume") if paused else _("Pause"))
        if paused:
            self.pause_btn.get_style_context().add_class("suggested-action")
        else:
            self.pause_btn.get_style_context().remove_class("suggested-action")
        self.cancel_btn.set_visible(active)
        self.start_now_btn.set_visible(run.status is RunStatus.QUEUED)
        self.unlock_btn.set_visible(False)
        self.retry_btn.set_visible(run.status is RunStatus.FAILED and not run.preview)
        self.dismiss_btn.set_visible(not active)

        bar_ctx = self.bar.get_style_context()
        (bar_ctx.add_class if paused or not active else bar_ctx.remove_class)("paused")
        if run.status is RunStatus.SUCCESS:
            self.bar.set_fraction(1.0)
        elif run.status in (RunStatus.RUNNING, RunStatus.PAUSED) and s.percent == 0 and s.bytes_done == 0:
            self.bar.pulse()
        else:
            self.bar.set_fraction(s.fraction if s.percent else 0.0)

        total = s.bytes_total_estimate
        self.metric_values["copied"].set_text(
            _("{done} of {total}").format(done=format_bytes(s.bytes_done), total=format_bytes(total)) if total and active
            else format_bytes(s.bytes_done))
        self.metric_values["speed"].set_text(f"{format_bytes(s.speed_bps)}/s" if run.status is RunStatus.RUNNING and s.speed_bps else "—")
        if paused and run.paused_since:
            self.metric_names["eta"].set_text(_("Paused for"))
            self.metric_values["eta"].set_text(format_duration(time.time() - run.paused_since))
        elif active:
            self.metric_names["eta"].set_text(_("Time left"))
            self.metric_values["eta"].set_text(format_duration(s.eta_seconds) if s.eta_seconds else "—")
        else:
            self.metric_names["eta"].set_text(_("Took"))
            self.metric_values["eta"].set_text(format_duration((run.finished or time.time()) - run.started))
        self.metric_values["files"].set_text(
            _("{done} of {total}").format(done=f"{s.files_done:,}", total=f"{s.files_total:,}") if s.files_total else f"{s.files_done:,}")
        self.spark.set_values(run.speed_history)
        self.spark.set_visible(active)
        self.current.set_text(s.current_file if active else "")
        self.current.get_parent().set_visible(bool(active and s.current_file))

        note, note_kind = "", ""
        if run.status is RunStatus.QUEUED:
            note = run.queued_reason
        elif run.status is RunStatus.WAITING:
            note, note_kind = run.queued_reason, "lfc-warn"
        elif run.status is RunStatus.RUNNING and run.step_description and len(run.plan.steps if run.plan else []) > 1:
            note = run.step_description
        elif paused:
            note = _("If a drive is unplugged while paused, the job stops. Run it again later and it continues from the partial files.")
        elif not active:
            note = run.message + (f" {run.fix}" if run.fix else "")
            note_kind = {"failed": "lfc-err", "warning": "lfc-warn", "success": "lfc-ok"}.get(run.status.value, "")
        self.note.set_text(note)
        nctx = self.note.get_style_context()
        for c in ("lfc-err", "lfc-warn", "lfc-ok"):
            nctx.remove_class(c)
        if note_kind:
            nctx.add_class(note_kind)
        self.note.set_visible(bool(note))

        if len(run.log_lines) != self._log_count:
            self._log_count = len(run.log_lines)
            buf = self.log_view.get_buffer()
            buf.set_text("\n".join(run.log_lines[-200:]))
            if self.log_expander.get_expanded():
                self.log_view.scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0)
