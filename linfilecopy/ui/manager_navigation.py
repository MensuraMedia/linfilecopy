"""Page registry and navigation (pattern from gtk-python-dashboard-starter)."""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402


class NavigationManager:
    """Keeps the page stack and notifies listeners when the visible page changes."""

    def __init__(self) -> None:
        self.pages: dict[str, Gtk.Widget] = {}
        self.stack: Gtk.Stack | None = None
        self.current: str | None = None
        self._callbacks: list[Callable[[str], None]] = []

    def set_stack(self, stack: Gtk.Stack) -> None:
        self.stack = stack

    def register_page(self, page_id: str, page: Gtk.Widget) -> None:
        self.pages[page_id] = page

    def on_navigate(self, callback: Callable[[str], None]) -> None:
        self._callbacks.append(callback)

    def navigate_to(self, page_id: str) -> None:
        if self.stack is None or page_id not in self.pages or page_id == self.current:
            return
        self.stack.set_visible_child_name(page_id)
        self.current = page_id
        page = self.pages[page_id]
        if hasattr(page, "on_shown"):
            page.on_shown()
        for cb in self._callbacks:
            cb(page_id)
