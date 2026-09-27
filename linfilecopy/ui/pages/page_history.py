"""History & Logs page (placeholder until its phase is implemented)."""
from __future__ import annotations

from linfilecopy.i18n import _
from linfilecopy.ui.pages.page_base import BasePage


class HistoryPage(BasePage):
    page_id = "history"
    title = _("History & Logs")

    def build_content(self) -> None:
        self.add_title(self.title)
