"""Live card for one run (B3, B4, #11): progress, speed graph, metrics, log, controls."""
from __future__ import annotations

import math
import time
from typing import Callable

import cairo
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

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


class ProgressRing(Gtk.DrawingArea):
    """Compact circular progress: a coloured arc over a dim track with the
    percentage in the centre. The colour follows the run's status. While the
    run is indeterminate (running, no percentage yet) a short arc rotates,
    mirroring the progress bar's pulse."""

    SPIN_MS = 33          # ~30 fps while indeterminate
    SPIN_STEP = 0.13      # radians per frame
    SWEEP = math.pi * 0.55  # length of the spinning arc

    def __init__(self, diameter: int = 50) -> None:
        super().__init__()
        self.set_size_request(diameter, diameter)
        self._fraction = 0.0
        self._text = ""
        self._token = "lfc_accent"
        self._indeterminate = False
        self._spin = -math.pi / 2
        self._anim_id = 0
        self.connect("draw", self._draw)
        self.connect("map", lambda *_: self._sync_anim())
        self.connect("unmap", lambda *_: self._stop_anim())
        self.connect("destroy", lambda *_: self._stop_anim())
        self.get_accessible().set_name(_("Progress"))

    def set_progress(self, fraction: float, text: str, token: str,
                     indeterminate: bool = False) -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        self._text = text
        self._token = token
        if indeterminate != self._indeterminate:
            self._indeterminate = indeterminate
            self._sync_anim()
        self.queue_draw()

    # ----- indeterminate animation lifecycle ----------------------------------
    def _sync_anim(self) -> None:
        if self._indeterminate and self._anim_id == 0 and self.get_mapped():
            self._anim_id = GLib.timeout_add(self.SPIN_MS, self._on_frame)
        elif not self._indeterminate:
            self._stop_anim()

    def _stop_anim(self) -> None:
        if self._anim_id:
            GLib.source_remove(self._anim_id)
            self._anim_id = 0

    def _on_frame(self) -> bool:
        if not self._indeterminate:
            self._anim_id = 0
            return GLib.SOURCE_REMOVE
        self._spin = (self._spin + self.SPIN_STEP) % (2 * math.pi)
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    # ----- drawing ------------------------------------------------------------
    def _draw(self, widget: Gtk.Widget, cr) -> bool:  # type: ignore[no-untyped-def]
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        size = min(w, h)
        if size < 8:
            return False
        cx, cy = w / 2.0, h / 2.0
        lw = max(3.0, size * 0.12)
        r = size / 2.0 - lw / 2.0 - 1.0
        ctx = widget.get_style_context()
        _t, trough = ctx.lookup_color("lfc_trough")
        _c, col = ctx.lookup_color(self._token)
        fg = ctx.get_color(widget.get_state_flags())

        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_width(lw)
        # track
        cr.set_source_rgba(trough.red, trough.green, trough.blue, 1.0)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()

        top = -math.pi / 2  # 12 o'clock
        if self._indeterminate:
            a0 = self._spin
            self._arc(cr, cx, cy, r, a0, a0 + self.SWEEP, col, lw)
        elif self._fraction > 0:
            self._arc(cr, cx, cy, r, top, top + 2 * math.pi * self._fraction, col, lw)

        if self._text:
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL,
                                cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(size * 0.27)
            ext = cr.text_extents(self._text)
            cr.move_to(cx - ext.width / 2 - ext.x_bearing,
                       cy - ext.height / 2 - ext.y_bearing)
            cr.set_source_rgba(fg.red, fg.green, fg.blue, fg.alpha)
            cr.show_text(self._text)
        return False

    def _arc(self, cr, cx, cy, r, a0, a1, col, lw) -> None:  # type: ignore[no-untyped-def]
        # A linear gradient from top to bottom-right across the ring gives the
        # arc a soft two-tone sweep (like the reference ring) while staying on
        # the app's accent/status colour. Round caps match the progress bar.
        light = _blend(col, (1.0, 1.0, 1.0), 0.28)
        grad = cairo.LinearGradient(cx, cy - r, cx + r, cy + r)
        grad.add_color_stop_rgba(0.0, col.red, col.green, col.blue, 1.0)
        grad.add_color_stop_rgba(1.0, *light, 1.0)
        cr.set_source(grad)
        cr.arc(cx, cy, r, a0, a1)
        cr.stroke()


def _blend(c, white, t: float):  # type: ignore[no-untyped-def]
    """Lighten a Gdk.RGBA toward white by fraction t; returns an (r,g,b) tuple."""
    return (c.red + (white[0] - c.red) * t,
            c.green + (white[1] - c.green) * t,
            c.blue + (white[2] - c.blue) * t)


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

        prog_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.ring = ProgressRing(50)
        self.ring.set_valign(Gtk.Align.CENTER)
        prog_row.pack_start(self.ring, False, False, 0)
        self.bar = Gtk.ProgressBar()
        add_classes(self.bar, "lfc-progress")
        self.bar.set_valign(Gtk.Align.CENTER)
        prog_row.pack_start(self.bar, True, True, 0)
        self.pack_start(prog_row, False, False, 0)

        # Four columns when wide, two when narrow.
        metrics = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=2,
                              max_children_per_line=4, column_spacing=18, row_spacing=8)
        self.metric_values: dict[str, Gtk.Label] = {}
        self.metric_names: dict[str, Gtk.Label] = {}
        for key, title in (("copied", _("Copied")), ("speed", _("Speed")), ("eta", _("Time left")), ("files", _("Files copied"))):
            cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            n = label(title, "lfc-dim", "lfc-small")
            v = label("—", "lfc-metric-value", ellipsize=True)
            cell.pack_start(n, False, False, 0)
            cell.pack_start(v, False, False, 0)
            metrics.add(cell)
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
        greyed = paused or run.status in (RunStatus.CANCELLED, RunStatus.QUEUED, RunStatus.WAITING)
        (bar_ctx.add_class if greyed else bar_ctx.remove_class)("paused")
        if run.status is RunStatus.SUCCESS:
            self.bar.set_fraction(1.0)
        elif run.status in (RunStatus.RUNNING, RunStatus.PAUSED) and s.percent == 0 and s.bytes_done == 0:
            self.bar.pulse()
        else:
            self.bar.set_fraction(s.fraction if s.percent else 0.0)

        # Circular glance indicator next to the bar, coloured by status.
        if run.status is RunStatus.SUCCESS:
            self.ring.set_progress(1.0, "100%", "lfc_ok")
        elif run.status is RunStatus.RUNNING and s.percent == 0 and s.bytes_done == 0:
            self.ring.set_progress(0.0, "", "lfc_accent", indeterminate=True)
        else:
            token = {"info": "lfc_accent", "ok": "lfc_ok", "err": "lfc_err",
                     "warn": "lfc_warn"}.get(kind, "lfc_dim")
            self.ring.set_progress(s.fraction if s.percent else 0.0,
                                   f"{s.percent}%" if s.percent else "", token)

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
        # rsync's total counts folders too, so show files copied (and entries checked while running).
        files = f"{s.files_done:,}"
        if active and s.files_total:
            files += " · " + _("{n} of {total} checked").format(n=f"{s.files_checked:,}", total=f"{s.files_total:,}")
        self.metric_values["files"].set_text(files)
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
