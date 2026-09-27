"""Headless command line, used by scheduled runs (#19) and for scripting.

    linfilecopy run <job-id> [--dry-run] [--quiet]
    linfilecopy preview <job-id>
    linfilecopy list
    linfilecopy validate <job-id>

Exit status: 0 success, 1 failed, 2 usage error, 3 cancelled, 4 finished with
warnings. Runs are recorded in history like GUI runs. Notifications are sent
over D-Bus (org.freedesktop.Notifications) when a desktop session is present.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time

from linfilecopy import paths
from linfilecopy.i18n import _

SUBCOMMANDS = ("run", "list", "preview", "validate")
EXIT = {"success": 0, "failed": 1, "cancelled": 3, "warning": 4}


def _notify(title: str, body: str, icon: str) -> None:
    """Best-effort desktop notification without GTK."""
    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                      "org.freedesktop.Notifications", "Notify",
                      GLib.Variant("(susssasa{sv}i)", ("LinFileCopy", 0, icon, title, body, [], {}, -1)),
                      None, Gio.DBusCallFlags.NONE, 3000, None)
    except Exception:  # noqa: BLE001 - no session bus under cron is normal
        pass


def _load(job_id: str):  # type: ignore[no-untyped-def]
    from linfilecopy.model.store import JobStore

    store = JobStore()
    try:
        job = store.get(job_id)
    except ValueError:
        job = None
    if job is None:
        print(_("No job with id {id}. Use 'linfilecopy list'.").format(id=job_id), file=sys.stderr)
    return job


def _services():  # type: ignore[no-untyped-def]
    from linfilecopy.engine import tools
    from linfilecopy.engine.drives import UDisksClient
    from linfilecopy.engine.runner import EngineServices
    from linfilecopy.model.history import HistoryStore

    caps = tools.detect()
    return EngineServices(HistoryStore(), UDisksClient() if caps.udisks.available else None, caps)


def cmd_list(_args: argparse.Namespace) -> int:
    from linfilecopy.engine.scheduler import describe_schedule
    from linfilecopy.model.store import JobStore

    jobs = JobStore().list()
    if not jobs:
        print(_("No saved jobs."))
    for job in jobs:
        print(f"{job.id:32} {job.mode.value:8} {job.name}")
        print(f"{'':32} {job.source.path} -> {job.destination.path}")
        print(f"{'':32} {describe_schedule(job)}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from linfilecopy.engine import planner

    job = _load(args.job)
    if job is None:
        return 2
    svc = _services()
    drives = svc.udisks.list_drives() if svc.udisks else []
    caps = svc.capabilities
    env = planner.gather_env(job, drives, caps.rsync.path, caps.rsync_version, caps.ionice.available,
                             caps.nice.available, caps.udisks.available)
    plan = planner.plan_job(job, env)
    for issue in plan.issues:
        print(f"[{issue.level}] {issue.message} {issue.fix}".rstrip())
    print(plan.display_text())
    return 0 if plan.runnable else 1


def _execute(args: argparse.Namespace, preview: bool) -> int:
    from linfilecopy.engine.runner import JobRun, RunHooks
    from linfilecopy.formatting import format_bytes
    from linfilecopy.model.enums import RunStatus, Trigger

    job = _load(args.job)
    if job is None:
        return 2
    paths.ensure_dirs()
    trigger = Trigger(args.trigger) if getattr(args, "trigger", None) else Trigger.SCHEDULE
    quiet = getattr(args, "quiet", False) or not sys.stdout.isatty()
    last = [0.0]

    def on_update(run: JobRun) -> None:
        if quiet or time.monotonic() - last[0] < 1:
            return
        last[0] = time.monotonic()
        s = run.snapshot
        print(f"\r{run.status.value:9} {s.percent:3d}%  {format_bytes(s.bytes_done):>10}  "
              f"{format_bytes(s.speed_bps)}/s  {s.current_file[-50:]:50}", end="", flush=True)

    def passphrase(_run: JobRun, drive) -> str | None:  # type: ignore[no-untyped-def]
        try:
            from linfilecopy.ui.manager_secrets import lookup
        except (ImportError, ValueError):
            return None
        return lookup(drive.uuid)

    run = JobRun(job, _services(), RunHooks(on_update=on_update, request_passphrase=passphrase), trigger,
                 dry_run=getattr(args, "dry_run", False), preview=preview)
    signal.signal(signal.SIGTERM, lambda *_a: run.cancel())
    signal.signal(signal.SIGINT, lambda *_a: run.cancel())
    run.start()
    while run.active:
        run.join(0.5)
    if not quiet:
        print()
    if preview:
        for c in run.changes:
            print(f"{c.kind.value:8} {c.path}")
    print(f"{run.status.value}: {run.message} {run.fix}".rstrip())
    if not preview and not run.dry_run and trigger is not Trigger.MANUAL:
        if run.status is RunStatus.FAILED and job.logging.notify_failure:
            _notify(_("{job} failed").format(job=job.name), f"{run.message}\n{run.fix}", "dialog-error")
        elif run.status in (RunStatus.SUCCESS, RunStatus.WARNING) and job.logging.notify_success:
            _notify(_("{job} finished").format(job=job.name), run.message, "emblem-ok")
    if job.schedule.kind.value == "once" and trigger is Trigger.SCHEDULE and not preview:
        try:
            from linfilecopy.engine import scheduler

            scheduler.remove(job.id)
        except Exception:  # noqa: BLE001
            pass
    return EXIT.get(run.status.value, 1)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="linfilecopy", description=_("Run LinFileCopy jobs without the window."))
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run", help=_("run a saved job"))
    p.add_argument("job")
    p.add_argument("--dry-run", action="store_true", help=_("show progress but change nothing"))
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--trigger", choices=["manual", "schedule", "file_change", "drive_connected"], default="schedule")
    p.set_defaults(func=lambda a: _execute(a, preview=False))
    p = sub.add_parser("preview", help=_("list what a job would change"))
    p.add_argument("job")
    p.set_defaults(func=lambda a: _execute(a, preview=True), trigger="manual")
    p = sub.add_parser("list", help=_("list saved jobs"))
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("validate", help=_("check a job and print its plan"))
    p.add_argument("job")
    p.set_defaults(func=cmd_validate)
    args = parser.parse_args(argv)
    from linfilecopy.log import setup_logging

    setup_logging()
    return int(args.func(args))
