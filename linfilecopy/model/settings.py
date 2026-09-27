"""Application-wide preferences stored as JSON in the config directory."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from linfilecopy import paths
from linfilecopy.log import get_logger

_log = get_logger(__name__)

STYLES = ("system", "light", "dark")
ACCENTS: dict[str, str] = {
    "blue": "#3584e4",
    "teal": "#2190a4",
    "green": "#3a944a",
    "yellow": "#c88800",
    "orange": "#ed5b00",
    "red": "#e62d42",
    "purple": "#9141ac",
    "slate": "#6f8396",
}


@dataclass
class AppSettings:
    """User preferences. Unknown keys in the file are ignored; missing keys use defaults."""

    style: str = "system"
    accent: str = "blue"
    preview_new_jobs: bool = True
    confirm_deletes: bool = True
    keep_in_tray: bool = True
    notify_success: bool = True
    notify_failure: bool = True
    history_days: int = 90
    twoway_delete_guard_percent: int = 50
    show_system_partitions: bool = False
    simple_view_default: bool = True

    def normalised(self) -> "AppSettings":
        """Clamp values into their valid ranges."""
        if self.style not in STYLES:
            self.style = "system"
        if self.accent not in ACCENTS:
            self.accent = "blue"
        self.history_days = max(1, min(3650, int(self.history_days)))
        self.twoway_delete_guard_percent = max(1, min(100, int(self.twoway_delete_guard_percent)))
        return self

    @classmethod
    def load(cls, path: Path | None = None) -> "AppSettings":
        path = path or paths.settings_file()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as exc:
            _log.warning("settings unreadable (%s); using defaults", exc)
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known}).normalised()

    def save(self, path: Path | None = None) -> None:
        path = path or paths.settings_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self.normalised()), indent=2), encoding="utf-8")
        tmp.replace(path)
