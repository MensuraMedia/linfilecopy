"""Scheduling (#19): systemd user timers, with crontab as fallback.

Timed runs execute ``python3 -m linfilecopy run <job-id>`` headlessly. Every
schedule is visible and reversible: unit files live in
``~/.config/systemd/user/linfilecopy-<id>.{service,timer}``; cron entries are
wrapped in ``# linfilecopy:<id> BEGIN/END`` markers and nothing else in the
user's crontab is touched.
"""
from __future__ import annotations

import datetime as dt
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from linfilecopy.i18n import _
from linfilecopy.model import cron
from linfilecopy.model.enums import ScheduleBackend, ScheduleKind
from linfilecopy.model.job import JOB_ID_RE, ScheduleOptions, SyncJob

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]   # index 0 = Monday (model convention)
UNIT_PREFIX = "linfilecopy-"
CRON_BEGIN = "# linfilecopy:{id} BEGIN"
CRON_END = "# linfilecopy:{id} END"

Runner = Callable[[list[str], str | None], tuple[int, str]]


class ScheduleError(Exception):
    """User-facing scheduling failure."""


IN_FLATPAK = os.path.exists("/.flatpak-info")
FLATPAK_ID = "io.github.mensuramedia.LinFileCopy"


def _run(argv: list[str], stdin: str | None = None) -> tuple[int, str]:
    if IN_FLATPAK and argv and argv[0] in ("systemctl", "crontab"):
        argv = ["flatpak-spawn", "--host", *argv]   # timers and crontab live on the host
    try:
        proc = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# ---------------------------------------------------------------------------
# describing and computing

def _hm(sch: ScheduleOptions) -> tuple[int, int]:
    h, m = (sch.time or "03:00").split(":")
    return int(h), int(m)


def describe_schedule(job: SyncJob) -> str:
    sch = job.schedule
    days_all = sorted(set(sch.weekdays)) == list(range(7))
    if sch.kind is ScheduleKind.NONE:
        return _("Not scheduled")
    if sch.kind is ScheduleKind.HOURLY:
        text = _("Every hour at :{m:02d}").format(m=sch.minute)
    elif sch.kind is ScheduleKind.DAILY:
        text = _("Daily at {t}").format(t=sch.time)
    elif sch.kind is ScheduleKind.WEEKLY:
        names = ", ".join(DAY_NAMES[d] for d in sorted(set(sch.weekdays)))
        text = _("Daily at {t}").format(t=sch.time) if days_all else _("{days} at {t}").format(days=names, t=sch.time)
    elif sch.kind is ScheduleKind.ONCE:
        text = _("Once on {d} at {t}").format(d=sch.once_date, t=sch.time)
    else:
        text = _("Custom: {expr}").format(expr=sch.cron)
    if not sch.enabled:
        text += " · " + _("paused")
    return text


def cron_expression(sch: ScheduleOptions) -> str | None:
    """Equivalent 5-field cron expression (None for NONE; ONCE uses the date)."""
    if sch.kind is ScheduleKind.NONE:
        return None
    if sch.kind is ScheduleKind.HOURLY:
        return f"{sch.minute} * * * *"
    if sch.kind is ScheduleKind.CUSTOM:
        return sch.cron.strip()
    h, m = _hm(sch)
    if sch.kind is ScheduleKind.DAILY:
        return f"{m} {h} * * *"
    if sch.kind is ScheduleKind.WEEKLY:
        dows = sorted({(d + 1) % 7 for d in sch.weekdays})   # model Monday=0 -> cron Monday=1
        return f"{m} {h} * * {','.join(map(str, dows)) or '*'}"
    if sch.kind is ScheduleKind.ONCE:
        y, mo, d = (int(x) for x in sch.once_date.split("-"))
        return f"{m} {h} {d} {mo} *"
    return None


def next_run(job: SyncJob, after: dt.datetime | None = None) -> dt.datetime | None:
    sch = job.schedule
    after = after or dt.datetime.now()
    if sch.kind is ScheduleKind.NONE or not sch.enabled:
        return None
    try:
        if sch.kind is ScheduleKind.ONCE:
            h, m = _hm(sch)
            when = dt.datetime.strptime(sch.once_date, "%Y-%m-%d").replace(hour=h, minute=m)
            return when if when > after else None
        expr = cron_expression(sch)
        return cron.parse(expr).next_after(after) if expr else None
    except (ValueError, cron.CronError):
        return None


def _compress(values: list[int], width: int = 2) -> str:
    """[1,2,3,5] -> "01..03,05" (systemd calendar syntax)."""
    out, i = [], 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[j + 1] == values[j] + 1:
            j += 1
        a, b = values[i], values[j]
        out.append(f"{a:0{width}d}" if a == b else f"{a:0{width}d}..{b:0{width}d}")
        i = j + 1
    return ",".join(out)


def on_calendar(sch: ScheduleOptions) -> str:
    """systemd OnCalendar value for a schedule. Raises ScheduleError if not expressible."""
    if sch.kind is ScheduleKind.ONCE:
        return f"{sch.once_date} {sch.time}:00"
    expr = cron_expression(sch)
    if not expr:
        raise ScheduleError(_("The job has no schedule."))
    spec = cron.parse(expr)
    if spec.days_restricted and spec.weekdays_restricted:
        raise ScheduleError(_("systemd cannot express \"day of month OR weekday\"; use cron for this schedule."))
    full = lambda s, lo, hi: sorted(s) == list(range(lo, hi + 1))  # noqa: E731
    minute = "*" if full(spec.minutes, 0, 59) else _compress(sorted(spec.minutes))
    hour = "*" if full(spec.hours, 0, 23) else _compress(sorted(spec.hours))
    dom = "*" if not spec.days_restricted else _compress(sorted(spec.days))
    month = "*" if full(spec.months, 1, 12) else _compress(sorted(spec.months))
    dow = ""
    if spec.weekdays_restricted:
        names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        dow = ",".join(names[d] for d in sorted(spec.weekdays, key=lambda d: (d + 6) % 7)) + " "
    return f"{dow}*-{month}-{dom} {hour}:{minute}:00"


# ---------------------------------------------------------------------------
# command line to run

def run_command(job_id: str) -> list[str]:
    """argv that runs a job headlessly with the current interpreter."""
    if IN_FLATPAK:
        return ["flatpak", "run", "--command=linfilecopy", FLATPAK_ID, "run", job_id]
    exe = shutil.which("linfilecopy")
    if exe and os.path.realpath(sys.executable) != os.path.realpath(exe):
        return [exe, "run", job_id]
    return [sys.executable, "-m", "linfilecopy", "run", job_id]


def _package_root() -> str:
    return str(Path(__file__).resolve().parent.parent.parent)


# ---------------------------------------------------------------------------
# backends

@dataclass
class Scheduler:
    """Installs, lists and removes schedules. Injectable for tests."""

    unit_dir: Path = Path.home() / ".config" / "systemd" / "user"
    runner: Runner = _run
    systemd_available: bool | None = None
    cron_available: bool | None = None

    def __post_init__(self) -> None:
        if self.systemd_available is None:
            code, out = self.runner(["systemctl", "--user", "show-environment"], None)
            self.systemd_available = code == 0 and bool(out.strip())
        if self.cron_available is None:
            if IN_FLATPAK:
                self.cron_available = self.runner(["crontab", "-l"], None)[0] in (0, 1)
            else:
                self.cron_available = shutil.which("crontab") is not None

    # ----- selection -------------------------------------------------------------
    def backend_for(self, job: SyncJob) -> ScheduleBackend:
        want = job.schedule.backend
        if want is ScheduleBackend.SYSTEMD:
            if not self.systemd_available:
                raise ScheduleError(_("systemd user timers are not available on this system."))
            return want
        if want is ScheduleBackend.CRON:
            if not self.cron_available:
                raise ScheduleError(_("crontab is not installed."))
            return want
        if self.systemd_available:
            try:
                on_calendar(job.schedule)
                return ScheduleBackend.SYSTEMD
            except ScheduleError:
                if not self.cron_available:
                    raise
        if self.cron_available:
            return ScheduleBackend.CRON
        raise ScheduleError(_("Neither systemd user timers nor crontab are available, so jobs cannot be scheduled."))

    # ----- apply -------------------------------------------------------------------
    def apply(self, job: SyncJob) -> ScheduleBackend | None:
        """Make the installed schedule match ``job.schedule`` (install, update or remove)."""
        if not JOB_ID_RE.match(job.id):
            raise ScheduleError(_("Invalid job id."))
        self.remove(job.id)
        if job.schedule.kind is ScheduleKind.NONE:
            return None
        backend = self.backend_for(job)
        if backend is ScheduleBackend.SYSTEMD:
            self._install_systemd(job)
        else:
            self._install_cron(job)
        return backend

    def remove(self, job_id: str) -> None:
        if not JOB_ID_RE.match(job_id):
            raise ScheduleError(_("Invalid job id."))
        name = f"{UNIT_PREFIX}{job_id}"
        timer, service = self.unit_dir / f"{name}.timer", self.unit_dir / f"{name}.service"
        if timer.exists() or service.exists():
            if self.systemd_available:
                self.runner(["systemctl", "--user", "disable", "--now", f"{name}.timer"], None)
            for p in (timer, service):
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
            if self.systemd_available:
                self.runner(["systemctl", "--user", "daemon-reload"], None)
        if self.cron_available:
            current = self._read_crontab()
            cleaned = _strip_cron_block(current, job_id)
            if cleaned != current:
                self._write_crontab(cleaned)

    def installed(self) -> dict[str, ScheduleBackend]:
        out: dict[str, ScheduleBackend] = {}
        if self.unit_dir.is_dir():
            for p in self.unit_dir.glob(f"{UNIT_PREFIX}*.timer"):
                out[p.stem[len(UNIT_PREFIX):]] = ScheduleBackend.SYSTEMD
        if self.cron_available:
            for line in self._read_crontab().splitlines():
                if line.startswith("# linfilecopy:") and line.endswith(" BEGIN"):
                    out[line[len("# linfilecopy:"):-len(" BEGIN")]] = ScheduleBackend.CRON
        return out

    # ----- systemd -------------------------------------------------------------------
    def unit_texts(self, job: SyncJob) -> tuple[str, str]:
        sch = job.schedule
        cmd = " ".join(shlex.quote(a) for a in run_command(job.id))
        service = (
            "[Unit]\n"
            f"Description=LinFileCopy: {job.name}\n"
            "Documentation=https://github.com/MensuraMedia/linfilecopy\n"
            + ("ConditionACPower=true\n" if sch.ac_power_only else "")
            + "\n[Service]\nType=oneshot\n"
            f"Environment=PYTHONPATH={_package_root()}\n"
            f"ExecStart={cmd}\n"
            "Nice=10\n"
        )
        timer = (
            "[Unit]\n"
            f"Description=Schedule for LinFileCopy job {job.name}\n\n"
            "[Timer]\n"
            f"OnCalendar={on_calendar(sch)}\n"
            f"Persistent={'true' if sch.persistent else 'false'}\n"
            f"Unit={UNIT_PREFIX}{job.id}.service\n\n"
            "[Install]\nWantedBy=timers.target\n"
        )
        return service, timer

    def _install_systemd(self, job: SyncJob) -> None:
        service, timer = self.unit_texts(job)
        self.unit_dir.mkdir(parents=True, exist_ok=True)
        name = f"{UNIT_PREFIX}{job.id}"
        (self.unit_dir / f"{name}.service").write_text(service, encoding="utf-8")
        (self.unit_dir / f"{name}.timer").write_text(timer, encoding="utf-8")
        code, out = self.runner(["systemctl", "--user", "daemon-reload"], None)
        if code != 0:
            raise ScheduleError(_("systemd could not reload: {err}").format(err=out.strip()))
        verb = ["enable", "--now"] if job.schedule.enabled else ["disable", "--now"]
        code, out = self.runner(["systemctl", "--user", *verb, f"{name}.timer"], None)
        if code != 0:
            raise ScheduleError(_("systemd could not {verb} the timer: {err}").format(verb=verb[0], err=out.strip()))

    # ----- cron ----------------------------------------------------------------------------
    def cron_block(self, job: SyncJob) -> str:
        expr = cron_expression(job.schedule)
        env = f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{os.getuid()}/bus PYTHONPATH={shlex.quote(_package_root())}"
        cmd = " ".join(shlex.quote(a) for a in run_command(job.id))
        line = f"{expr} {env} {cmd} >/dev/null 2>&1"
        if not job.schedule.enabled:
            line = "#disabled# " + line
        return "\n".join([CRON_BEGIN.format(id=job.id), line, CRON_END.format(id=job.id)])

    def _read_crontab(self) -> str:
        code, out = self.runner(["crontab", "-l"], None)
        return out if code == 0 else ""

    def _write_crontab(self, text: str) -> None:
        code, out = self.runner(["crontab", "-"], text if text.endswith("\n") or not text else text + "\n")
        if code != 0:
            raise ScheduleError(_("crontab could not be updated: {err}").format(err=out.strip()))

    def _install_cron(self, job: SyncJob) -> None:
        current = _strip_cron_block(self._read_crontab(), job.id).rstrip("\n")
        block = self.cron_block(job)
        self._write_crontab((current + "\n" if current else "") + block + "\n")


def _strip_cron_block(text: str, job_id: str) -> str:
    begin, end = CRON_BEGIN.format(id=job_id), CRON_END.format(id=job_id)
    out, skipping = [], False
    for line in text.splitlines():
        if line == begin:
            skipping = True
            continue
        if skipping and line == end:
            skipping = False
            continue
        if not skipping:
            out.append(line)
    return "\n".join(out) + ("\n" if out else "")


_default: Scheduler | None = None


def default() -> Scheduler:
    global _default
    if _default is None:
        _default = Scheduler()
    return _default


def remove(job_id: str) -> None:
    """Convenience used when a job is deleted."""
    default().remove(job_id)
