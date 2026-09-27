"""Desktop notifications for finished runs (B10, #18) via Gio.Notification."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from linfilecopy.engine.runner import JobRun  # noqa: E402
from linfilecopy.i18n import _  # noqa: E402
from linfilecopy.model.enums import RunStatus  # noqa: E402
from linfilecopy.ui.context import AppContext  # noqa: E402
from linfilecopy.ui.icons import icon_name  # noqa: E402


class NotificationManager:
    def __init__(self, app: Gtk.Application, ctx: AppContext) -> None:
        self.app = app
        self.ctx = ctx

    def run_finished(self, run: JobRun) -> None:
        if run.preview or run.dry_run:
            return
        s = self.ctx.settings
        job = run.job
        if run.status in (RunStatus.SUCCESS, RunStatus.WARNING):
            if not (s.notify_success and job.logging.notify_success):
                return
            title = _("{job} finished").format(job=job.name)
            body = run.message
            if any(line.endswith(_("can now be unplugged.")) for line in run.log_lines[-10:]):
                label = job.destination.volume_label or _("The drive")
                body += "\n" + _("{drive} was ejected and can be unplugged.").format(drive=label)
            icon = "status-success" if run.status is RunStatus.SUCCESS else "status-warning"
        elif run.status is RunStatus.FAILED:
            if not (s.notify_failure and job.logging.notify_failure):
                return
            title = _("{job} failed").format(job=job.name)
            body = run.message + (f"\n{run.fix}" if run.fix else "")
            icon = "status-failed"
        else:
            return
        n = Gio.Notification.new(title)
        n.set_body(body)
        n.set_icon(Gio.ThemedIcon.new(icon_name(icon)))
        target = GLib.Variant.new_string(run.id).print_(False)   # run ids are hex: safe to embed
        n.set_default_action(f"app.show-run({target})")
        if run.status is RunStatus.FAILED:
            n.add_button(_("Retry"), f"app.retry-run({target})")
            n.add_button(_("Open log"), f"app.open-log({target})")
            n.set_priority(Gio.NotificationPriority.HIGH)
        else:
            n.add_button(_("Show details"), f"app.show-run({target})")
        self.app.send_notification(f"run-{job.id}", n)

    def simple(self, key: str, title: str, body: str, icon: str = "misc-info",
               action: str | None = None, target: str | None = None, button: str | None = None) -> None:
        n = Gio.Notification.new(title)
        n.set_body(body)
        n.set_icon(Gio.ThemedIcon.new(icon_name(icon)))
        if action and button:
            n.add_button(button, f"{action}({GLib.Variant.new_string(target or '').print_(False)})")
        self.app.send_notification(key, n)
