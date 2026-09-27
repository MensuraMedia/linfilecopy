"""Shared application state handed to every page (no globals)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from linfilecopy.engine.tools import Capabilities
from linfilecopy.model.settings import AppSettings

if TYPE_CHECKING:  # pragma: no cover
    from linfilecopy.engine.runner import RunManager
    from linfilecopy.model.history import HistoryStore
    from linfilecopy.model.store import JobStore
    from linfilecopy.ui.manager_drives import DriveManager
    from linfilecopy.ui.manager_notify import NotificationManager
    from linfilecopy.ui.manager_theme import ThemeManager


@dataclass
class AppContext:
    """Long-lived services shared by the pages.

    Topics published on the main thread: ``capabilities``, ``drives``,
    ``run-updated``, ``run-finished``, ``jobs-changed``, ``history-changed``,
    ``settings-changed``, ``preview-mode``, ``action`` (header/shortcut
    actions forwarded to the visible page), ``edit-job``, ``schedules-changed``.
    """

    settings: AppSettings
    theme: "ThemeManager"
    capabilities: Capabilities | None = None
    jobs: "JobStore | None" = None
    history: "HistoryStore | None" = None
    runs: "RunManager | None" = None
    drives: "DriveManager | None" = None
    notifier: "NotificationManager | None" = None
    preview_mode: bool = False
    services: dict[str, Any] = field(default_factory=dict)
    _listeners: dict[str, list[Callable[..., None]]] = field(default_factory=dict)

    def subscribe(self, topic: str, callback: Callable[..., None]) -> None:
        self._listeners.setdefault(topic, []).append(callback)

    def publish(self, topic: str, *args: Any) -> None:
        """Notify listeners. Must be called on the GTK main thread."""
        for cb in list(self._listeners.get(topic, [])):
            cb(*args)

    def save_settings(self) -> None:
        self.settings.save()
        self.publish("settings-changed", self.settings)

    @property
    def window(self) -> Any:
        return self.services.get("window")
