"""Active Transfers: one live card per run (B3, B4, #11)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from linfilecopy.engine.runner import JobRun  # noqa: E402
from linfilecopy.i18n import _, ngettext  # noqa: E402
from linfilecopy.model.enums import RunStatus, Trigger  # noqa: E402
from linfilecopy.ui.components.component_dialogs import empty_state  # noqa: E402
from linfilecopy.ui.components.component_run_card import RunCardWidget  # noqa: E402
from linfilecopy.ui.pages.page_base import BasePage  # noqa: E402

TICK_MS = 1000   # refresh paused timers and ETA text


class TransfersPage(BasePage):
    page_id = "transfers"
    title = _("Active Transfers")

    def build_content(self) -> None:
        self.cards: dict[str, RunCardWidget] = {}
        self.cards_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.content.pack_start(self.cards_box, False, False, 0)
        self.empty = empty_state("empty-transfers", _("Nothing is running"),
                                 _("Start a job from the Job Designer, or wait for a schedule. Finished runs stay here until you dismiss them."))
        self.empty.set_margin_top(60)
        self.content.pack_start(self.empty, True, True, 0)
        self.ctx.subscribe("run-updated", self._on_run)
        self.connect("key-press-event", self._on_key)
        GLib.timeout_add(TICK_MS, self._tick)
        self._update_empty()

    def after_show_all(self) -> None:
        self._update_empty()

    def _on_run(self, run: JobRun) -> None:
        if run.preview:
            return   # previews live in their dialog
        card = self.cards.get(run.id)
        if card is None:
            card = RunCardWidget(run, self._dismiss, self._retry, self._start_now)
            self.cards[run.id] = card
            self.cards_box.pack_start(card, False, False, 0)
            self.cards_box.reorder_child(card, 0)
        card.update()
        self._update_empty()

    def _tick(self) -> bool:
        for card in self.cards.values():
            if card.run.status in (RunStatus.PAUSED, RunStatus.RUNNING):
                card.update()
        return GLib.SOURCE_CONTINUE

    def _dismiss(self, card: RunCardWidget) -> None:
        self.cards.pop(card.run.id, None)
        self.cards_box.remove(card)
        card.destroy()
        self._update_empty()

    def _retry(self, run: JobRun) -> None:
        if self.ctx.runs is not None:
            from linfilecopy.ui.manager_launch import start_interactive

            fresh = self.ctx.jobs.get(run.job.id) if self.ctx.jobs else None
            start_interactive(self.ctx, fresh or run.job, Trigger.RETRY)

    def _start_now(self, run: JobRun) -> None:
        if self.ctx.runs is not None:
            self.ctx.runs.start_now(run.id)

    def _update_empty(self) -> None:
        self.empty.set_visible(not self.cards)
        active = [c for c in self.cards.values() if c.run.active]
        win = self.ctx.window
        if win is not None:
            win.sidebar.set_count("transfers", len(active))
            running = any(c.run.status is RunStatus.RUNNING for c in self.cards.values())
            win.sidebar.set_activity("transfers", "running" if running else "idle" if active else "none")
            if win.nav.current == self.page_id:
                win.refresh_subtitle()

    def subtitle(self) -> str:
        runs = [c.run for c in self.cards.values()]
        running = sum(1 for r in runs if r.status in (RunStatus.RUNNING, RunStatus.PAUSED))
        waiting = sum(1 for r in runs if r.status in (RunStatus.QUEUED, RunStatus.WAITING))
        parts = [_("Active Transfers")]
        if running:
            parts.append(ngettext("{n} running", "{n} running", running).format(n=running))
        if waiting:
            parts.append(ngettext("{n} waiting", "{n} waiting", waiting).format(n=waiting))
        return " · ".join(parts)

    def _focused_card(self) -> RunCardWidget | None:
        focus = self.get_toplevel().get_focus() if self.get_toplevel() else None
        while focus is not None and not isinstance(focus, RunCardWidget):
            focus = focus.get_parent()
        if focus is not None:
            return focus
        active = [c for c in self.cards.values() if c.run.active]
        return active[0] if len(active) == 1 else None

    def _on_key(self, _w: Gtk.Widget, event: Gdk.EventKey) -> bool:
        focus = self.get_toplevel().get_focus()
        if isinstance(focus, (Gtk.Entry, Gtk.TextView)):
            return False
        card = self._focused_card()
        if card is None:
            return False
        if event.keyval == Gdk.KEY_space:
            card.toggle_pause()
            return True
        if event.keyval == Gdk.KEY_Escape:
            card.ask_cancel()
            return True
        return False
