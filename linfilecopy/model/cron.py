"""Minimal 5-field cron expression parser and next-run calculator.

Supports ``*``, numbers, ranges ``a-b``, steps ``*/n`` and ``a-b/n``, lists
``a,b`` and three-letter month/day names. Day-of-week uses cron numbering
(0 or 7 = Sunday). When both day-of-month and day-of-week are restricted,
cron runs when *either* matches; that rule is honoured here.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from linfilecopy.i18n import _

FIELD_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
FIELD_NAMES = [_("minute"), _("hour"), _("day of month"), _("month"), _("day of week")]
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
DAYS = {d: i for i, d in enumerate(["sun", "mon", "tue", "wed", "thu", "fri", "sat"])}


class CronError(ValueError):
    """Raised for an invalid expression; the message is user-facing."""


@dataclass(frozen=True)
class CronSpec:
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]      # 0 = Sunday .. 6 = Saturday
    days_restricted: bool
    weekdays_restricted: bool

    def matches(self, t: dt.datetime) -> bool:
        if t.minute not in self.minutes or t.hour not in self.hours or t.month not in self.months:
            return False
        cron_dow = (t.weekday() + 1) % 7  # Python Monday=0 -> cron Monday=1
        day_ok = t.day in self.days
        dow_ok = cron_dow in self.weekdays
        if self.days_restricted and self.weekdays_restricted:
            return day_ok or dow_ok
        return day_ok and dow_ok

    def next_after(self, start: dt.datetime, limit_days: int = 366 * 4) -> dt.datetime | None:
        """First matching minute strictly after ``start`` (None if none within the limit)."""
        t = start.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
        end = start + dt.timedelta(days=limit_days)
        while t <= end:
            if t.month not in self.months:
                t = (t.replace(day=1, hour=0, minute=0) + dt.timedelta(days=32)).replace(day=1)
                continue
            if not self._day_matches(t):
                t = (t + dt.timedelta(days=1)).replace(hour=0, minute=0)
                continue
            if t.hour not in self.hours:
                t = (t + dt.timedelta(hours=1)).replace(minute=0)
                continue
            if t.minute in self.minutes:
                return t
            t += dt.timedelta(minutes=1)
        return None

    def _day_matches(self, t: dt.datetime) -> bool:
        cron_dow = (t.weekday() + 1) % 7
        day_ok = t.day in self.days
        dow_ok = cron_dow in self.weekdays
        if self.days_restricted and self.weekdays_restricted:
            return day_ok or dow_ok
        return day_ok and dow_ok


def _value(token: str, index: int) -> int:
    t = token.lower()
    if index == 3 and t in MONTHS:
        return MONTHS[t]
    if index == 4 and t in DAYS:
        return DAYS[t]
    if not t.isdigit():
        raise CronError(_("'{token}' is not valid in the {field} field").format(token=token, field=FIELD_NAMES[index]))
    return int(t)


def _parse_field(text: str, index: int) -> set[int]:
    lo, hi = FIELD_RANGES[index]
    values: set[int] = set()
    for part in text.split(","):
        if not part:
            raise CronError(_("Empty item in the {field} field").format(field=FIELD_NAMES[index]))
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) == 0:
                raise CronError(_("Invalid step '/{step}' in the {field} field").format(step=step_text, field=FIELD_NAMES[index]))
            step = int(step_text)
        if part == "*":
            start, stop = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, stop = _value(a, index), _value(b, index)
        else:
            start = _value(part, index)
            stop = hi if step > 1 else start
        if not (lo <= start <= hi and lo <= stop <= hi) or start > stop:
            raise CronError(_("The {field} must be between {lo} and {hi}").format(field=FIELD_NAMES[index], lo=lo, hi=hi))
        values.update(range(start, stop + 1, step))
    if index == 4 and 7 in values:
        values.discard(7)
        values.add(0)
    return values


def parse(expr: str) -> CronSpec:
    """Parse a 5-field expression or raise :class:`CronError`."""
    fields = expr.split()
    if len(fields) != 5:
        raise CronError(_("A cron expression needs 5 fields: minute hour day month weekday"))
    sets = [_parse_field(f, i) for i, f in enumerate(fields)]
    return CronSpec(
        frozenset(sets[0]), frozenset(sets[1]), frozenset(sets[2]), frozenset(sets[3]), frozenset(sets[4]),
        days_restricted=fields[2] != "*", weekdays_restricted=fields[4] != "*",
    )


def is_valid(expr: str) -> bool:
    try:
        parse(expr)
        return True
    except CronError:
        return False
