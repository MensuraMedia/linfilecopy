"""XDG-compliant locations for configuration, data, state and logs."""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "linfilecopy"
PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var, "").strip()
    base = Path(value) if value and os.path.isabs(value) else Path.home() / default
    return base / APP_DIR_NAME


def config_dir() -> Path:
    """``$XDG_CONFIG_HOME/linfilecopy``: jobs and settings."""
    return _xdg("XDG_CONFIG_HOME", ".config")


def data_dir() -> Path:
    """``$XDG_DATA_HOME/linfilecopy``: history database and two-way state."""
    return _xdg("XDG_DATA_HOME", ".local/share")


def state_dir() -> Path:
    """``$XDG_STATE_HOME/linfilecopy``: run logs."""
    return _xdg("XDG_STATE_HOME", ".local/state")


def jobs_dir() -> Path:
    return config_dir() / "jobs"


def settings_file() -> Path:
    return config_dir() / "settings.json"


def history_db() -> Path:
    return data_dir() / "history.db"


def twoway_state_dir() -> Path:
    return data_dir() / "state"


def logs_dir() -> Path:
    return state_dir() / "logs"


def ensure_dirs() -> None:
    """Create every directory the app writes to."""
    for d in (jobs_dir(), data_dir(), twoway_state_dir(), logs_dir()):
        d.mkdir(parents=True, exist_ok=True)
