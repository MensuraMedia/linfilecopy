"""UI smoke + accessibility test. Needs a display:

    xvfb-run -a python3 -m unittest tests.ui_smoke -v

Builds the real application with a throw-away home and demo data, visits
every page (Simple and Advanced designer views included) and checks that:

* no page raises while building or being shown;
* every button that shows only an icon has an accessible name (tooltip or
  explicit name), so screen readers can announce it;
* every text entry and spin button has an accessible name or placeholder.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _label_text(widget) -> str:  # type: ignore[no-untyped-def]
    from gi.repository import Gtk

    if isinstance(widget, Gtk.Label):
        return widget.get_text().strip()
    if isinstance(widget, Gtk.Container):
        return " ".join(t for t in (_label_text(c) for c in widget.get_children()) if t)
    return ""


@unittest.skipUnless(HAS_DISPLAY, "needs a display (run under xvfb-run)")
class UiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
            os.environ[var] = os.path.join(cls.tmp.name, var.lower())
        os.environ["LFC_DEMO_DIR"] = os.path.join(cls.tmp.name, "demo")
        os.makedirs(os.environ["LFC_DEMO_DIR"])
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_pages_build_and_are_accessible(self) -> None:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk

        from linfilecopy.app import LinFileCopyApp
        from tools.demo_data import seed

        jobs = seed()
        app = LinFileCopyApp()
        errors: list[str] = []
        problems: list[str] = []
        visited: list[str] = []
        old_hook = sys.excepthook
        sys.excepthook = lambda t, v, tb: errors.append(f"{t.__name__}: {v}")

        def audit(root) -> None:  # type: ignore[no-untyped-def]
            def walk(w) -> None:  # type: ignore[no-untyped-def]
                if not w.get_visible():
                    return
                name = w.get_accessible().get_name() or ""
                tip = w.get_tooltip_text() or ""
                if isinstance(w, Gtk.Button) and not isinstance(w, Gtk.ModelButton):
                    if not _label_text(w) and not (name or tip):
                        problems.append(f"icon-only {type(w).__name__} without a name in {type(root).__name__}")
                if isinstance(w, Gtk.Entry) and not isinstance(w, Gtk.SpinButton):
                    if not (name or w.get_placeholder_text() or tip) and w.get_editable():
                        problems.append(f"Entry without a name in {type(root).__name__} (text={w.get_text()[:20]!r})")
                if isinstance(w, Gtk.SpinButton) and not (name or tip):
                    problems.append(f"SpinButton without a name in {type(root).__name__}")
                if isinstance(w, Gtk.Container):
                    for c in w.get_children():
                        walk(c)
            walk(root)

        def run() -> bool:
            win = app.window
            try:
                app.ctx.publish("edit-job", jobs["snapshot"])
                designer = win.page("designer")
                designer.view_switch.set_value("advanced")
                for sec in designer.sections.values():
                    sec.set_expanded(True)
                for page_id in ("dashboard", "designer", "transfers", "history", "scheduler", "settings"):
                    win.show_page(page_id)
                    while Gtk.events_pending():
                        Gtk.main_iteration()
                    visited.append(page_id)
                    audit(win.page(page_id))
                audit(win.get_titlebar())
                audit(win.sidebar)
            except Exception as exc:  # noqa: BLE001 - reported by the assertion below
                errors.append(repr(exc))
            app.quit()
            return False

        app.connect("activate", lambda *_a: GLib.timeout_add(1500, run))
        try:
            app.run([sys.argv[0]])
        finally:
            sys.excepthook = old_hook
        self.assertEqual(visited, ["dashboard", "designer", "transfers", "history", "scheduler", "settings"])
        self.assertEqual(errors, [])
        self.assertEqual(sorted(set(problems)), [])

    def test_regressions_from_ui_review(self) -> None:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk

        from linfilecopy.app import LinFileCopyApp
        from linfilecopy.model.enums import Mode, ScheduleKind
        from tools.demo_data import seed

        jobs = seed()
        app = LinFileCopyApp()
        results: dict[str, object] = {}
        errors: list[str] = []

        def pump() -> None:
            while Gtk.events_pending():
                Gtk.main_iteration()

        def run() -> bool:
            try:
                ctx, win = app.ctx, app.window
                job = jobs["docs"]
                designer = win.page("designer")
                ctx.publish("edit-job", ctx.jobs.get(job.id))
                pump()
                # 1. a schedule saved in the Scheduler survives a Designer save
                stored = ctx.jobs.get(job.id)
                stored.schedule.kind, stored.schedule.enabled = ScheduleKind.DAILY, True
                ctx.jobs.save(stored)
                ctx.publish("schedules-changed")
                designer.name_entry.set_text("Renamed")
                ctx.publish("action", "save-job")
                results["schedule_kind"] = ctx.jobs.get(job.id).schedule.kind
                # 2. a typed path is used by Ctrl+S without leaving the field
                new_dst = job.destination.path + "-typed"
                designer.dst_card.entry.set_text(new_dst)
                ctx.publish("action", "save-job")
                results["dst"] = ctx.jobs.get(job.id).destination.path == new_dst
                # 3. re-running a Mirror job from outside the designer does not start the real run
                mirror = ctx.jobs.get(job.id)
                mirror.mode, mirror.preview_first = Mode.MIRROR, False
                ctx.jobs.save(mirror)
                from linfilecopy.ui.manager_launch import start_interactive

                start_interactive(ctx, mirror)
                pump()
                results["real_runs"] = [r for r in ctx.runs.active() if not r.preview]
                for r in ctx.runs.active():
                    r.cancel()
                for w in Gtk.Window.list_toplevels():
                    if isinstance(w, Gtk.Dialog):
                        w.destroy()
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))
            app.quit()
            return False

        app.connect("activate", lambda *_a: GLib.timeout_add(1500, run))
        app.run([sys.argv[0]])
        self.assertEqual(errors, [])
        self.assertEqual(results["schedule_kind"], ScheduleKind.DAILY)
        self.assertTrue(results["dst"])
        self.assertEqual(results["real_runs"], [])


if __name__ == "__main__":
    unittest.main()
