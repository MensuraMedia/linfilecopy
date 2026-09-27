"""Human-readable formatting shared by the UI, notifications and the CLI."""
from __future__ import annotations


def format_bytes(n: float) -> str:
    """Human-readable size using decimal units (as file managers do)."""
    step = 1000.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < step or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= step
    return f"{n:.1f} PB"


def format_duration(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} min {s:02d} s"
    h, m = divmod(m, 60)
    return f"{h} h {m:02d} min"
