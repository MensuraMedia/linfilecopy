"""Shared application state handed to every page (no globals)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from linfilecopy.engine.tools import Capabilities
from linfilecopy.model.settings import AppSettings

if TYPE_CHECKING:  # pragma: no cover
    from linfilecopy.ui.manager_theme import ThemeManager


@dataclass
class AppContext:
    """Long-lived services. Later phases attach the job store, history, runner and drive monitor."""

    settings: AppSettings
    theme: "ThemeManager"
    capabilities: Capabilities | None = None
    services: dict[str, Any] = field(default_factory=dict)
    _listeners: dict[str, list[Callable[..., None]]] = field(default_factory=dict)

    def subscribe(self, topic: str, callback: Callable[..., None]) -> None:
        """Listen for app-level events such as ``"capabilities"`` or ``"jobs-changed"``."""
        self._listeners.setdefault(topic, []).append(callback)

    def publish(self, topic: str, *args: Any) -> None:
        """Notify listeners. Must be called on the GTK main thread."""
        for cb in list(self._listeners.get(topic, [])):
            cb(*args)

    def save_settings(self) -> None:
        self.settings.save()
        self.publish("settings-changed", self.settings)
