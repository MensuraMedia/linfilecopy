"""The one way interactive runs start (B2, B7, #4).

Every place a person can start a job — Designer Start/Preview, History and
Dashboard "Run again", Scheduler "Run now", Transfers and notification
"Retry" — goes through :func:`start_interactive`, so all of them honour:

* the global Preview mode (only show what would change),
* the job's "Always preview first",
* the "Confirm before deleting files" setting for Mirror (and two-way
  without trash): the exact deletions are listed before anything runs.

Scheduled and triggered runs are unattended by design and start directly.
"""
from __future__ import annotations

import copy

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from linfilecopy.engine.runner import JobRun  # noqa: E402
from linfilecopy.i18n import _  # noqa: E402
from linfilecopy.model.enums import Mode, RunStatus, Trigger  # noqa: E402
from linfilecopy.model.job import SyncJob  # noqa: E402
from linfilecopy.ui.components.component_common import label  # noqa: E402
from linfilecopy.ui.components.component_dialogs import PreviewDialog, confirm_delete, deletions, info  # noqa: E402
from linfilecopy.ui.context import AppContext  # noqa: E402

PREVIEW_OK = (RunStatus.SUCCESS, RunStatus.WARNING)


def needs_delete_confirmation(ctx: AppContext, job: SyncJob) -> bool:
    return ctx.settings.confirm_deletes and (
        job.mode is Mode.MIRROR or (job.mode is Mode.TWO_WAY and not job.twoway.use_trash))


def start_interactive(ctx: AppContext, job: SyncJob, trigger: Trigger = Trigger.MANUAL) -> None:
    """Start ``job`` the way a person expects, with every safety prompt."""
    if ctx.runs is None:
        return
    if ctx.preview_mode:
        open_preview(ctx, job, allow_run=False)
    elif job.preview_first:
        open_preview(ctx, job, allow_run=True, trigger=trigger)
    else:
        confirm_and_run(ctx, job, None, trigger)


def open_preview(ctx: AppContext, job: SyncJob, allow_run: bool = True, trigger: Trigger = Trigger.MANUAL) -> None:
    """Preview dialog; "Run for real" runs exactly the job that was previewed."""
    if ctx.runs is None:
        return
    snapshot = copy.deepcopy(job)
    run = ctx.runs.start(snapshot, preview=True)
    dest = job.destination.volume_label or job.destination.path
    callback = (lambda: confirm_and_run(ctx, snapshot, run, trigger)) if allow_run and not ctx.preview_mode else None
    PreviewDialog(ctx.window, run, callback, dest)


def confirm_and_run(ctx: AppContext, job: SyncJob, preview_run: JobRun | None, trigger: Trigger = Trigger.MANUAL) -> None:
    if ctx.runs is None:
        return
    job = copy.deepcopy(job)
    if needs_delete_confirmation(ctx, job):
        if preview_run is None:
            _preview_then(ctx, job, lambda run: confirm_and_run(ctx, job, run, trigger))
            return
        dels = deletions(preview_run.changes)
        if dels:
            dest_label = job.destination.volume_label or job.destination.path
            if not confirm_delete(ctx.window, dels, job.name, dest_label, job.source.path):
                return
    ctx.runs.start(job, trigger)
    if ctx.window is not None:
        ctx.window.show_page("transfers")


def _preview_then(ctx: AppContext, job: SyncJob, then) -> None:  # type: ignore[no-untyped-def]
    """Silent preview to count deletions, with a small wait dialog."""
    run = ctx.runs.start(job, preview=True)  # type: ignore[union-attr]
    dlg = Gtk.Dialog(transient_for=ctx.window, modal=True, title=_("Checking"))
    box = dlg.get_content_area()
    for side in ("top", "bottom", "start", "end"):
        getattr(box, f"set_margin_{side}")(20)
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    row.pack_start(Gtk.Spinner(active=True), False, False, 0)
    row.pack_start(label(_("Checking what would be deleted…")), False, False, 0)
    box.pack_start(row, False, False, 0)
    dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    dlg.connect("response", lambda d, _r: (run.cancel(), d.destroy()))
    dlg.show_all()

    def poll() -> bool:
        if run.active:
            return GLib.SOURCE_CONTINUE
        if dlg.get_visible():
            dlg.destroy()
            if run.status in PREVIEW_OK:
                then(run)
            else:
                info(ctx.window, _("The check failed"), f"{run.message}\n{run.fix}", True)
        return GLib.SOURCE_REMOVE

    GLib.timeout_add(250, poll)
