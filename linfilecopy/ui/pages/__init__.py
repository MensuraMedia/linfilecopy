"""Dashboard pages, one module per sidebar entry."""
from __future__ import annotations

from linfilecopy.ui.context import AppContext
from linfilecopy.ui.pages.page_base import BasePage


def build_pages(ctx: AppContext) -> list[BasePage]:
    """Instantiate every page in sidebar order."""
    from linfilecopy.ui.pages.page_dashboard import DashboardPage
    from linfilecopy.ui.pages.page_designer import DesignerPage
    from linfilecopy.ui.pages.page_history import HistoryPage
    from linfilecopy.ui.pages.page_scheduler import SchedulerPage
    from linfilecopy.ui.pages.page_settings import SettingsPage
    from linfilecopy.ui.pages.page_transfers import TransfersPage

    return [cls(ctx) for cls in (DashboardPage, DesignerPage, TransfersPage, HistoryPage, SchedulerPage, SettingsPage)]
