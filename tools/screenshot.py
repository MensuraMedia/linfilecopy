#!/usr/bin/env python3
"""Render the app headlessly and save PNG screenshots of pages.

Run under Xvfb:
    xvfb-run -a -s "-screen 0 1400x1000x24" python3 tools/screenshot.py \
        --page dashboard --width 1180 --height 780 --style dark --out /tmp/dash.png

Uses a throw-away XDG config/data/state directory unless --real-home is given,
so it never touches the user's jobs or history. ``--demo`` seeds example jobs
and history so pages show a realistic working state.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", action="append", default=[], help="page id (repeatable)")
    ap.add_argument("--width", type=int, default=1180)
    ap.add_argument("--height", type=int, default=780)
    ap.add_argument("--style", choices=["light", "dark", "system"], default="light")
    ap.add_argument("--out", default="shot.png", help="file, or directory when several pages")
    ap.add_argument("--demo", action="store_true", help="seed demo jobs and history")
    ap.add_argument("--real-home", action="store_true")
    ap.add_argument("--delay", type=int, default=900, help="ms to wait before capture")
    ap.add_argument("--action", action="append", default=[], help="page action to run before capture")
    ap.add_argument("--run-demo", help="with --demo: open this demo job (docs/music/snapshot/notes), slow it down and press Start")
    ap.add_argument("--open-demo", help="with --demo: open this demo job in the designer")
    ap.add_argument("--advanced", action="store_true", help="show the designer's Advanced view")
    ap.add_argument("--root", action="store_true", help="capture the whole screen (includes dialogs)")
    ap.add_argument("--demo-drives", action="store_true", help="show example drives instead of this machine's")
    args = ap.parse_args()

    if not args.real_home:
        tmp = tempfile.mkdtemp(prefix="lfc-shot-")
        for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
            os.environ[var] = os.path.join(tmp, var.lower())
    os.environ.setdefault("GTK_THEME", "Adwaita:dark" if args.style == "dark" else "Adwaita")

    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk

    if args.demo_drives:
        from tools.demo_drives import install

        install()
    from linfilecopy.app import LinFileCopyApp
    from linfilecopy.model.settings import AppSettings

    settings = AppSettings(style=args.style)
    settings.save()
    seed_result = {}
    if args.demo:
        from tools.demo_data import seed

        seed_result = seed()

    demo_jobs = {}
    if args.demo:
        demo_jobs = seed_result  # noqa: F821 - set below
    pages = args.page or ["dashboard"]
    app = LinFileCopyApp()

    def capture(win: Gtk.Window, name: str) -> None:
        gdk_win = Gdk.get_default_root_window() if args.root else win.get_window()
        w, h = gdk_win.get_width(), gdk_win.get_height()
        pb = Gdk.pixbuf_get_from_window(gdk_win, 0, 0, w, h)
        out = Path(args.out)
        if len(pages) > 1:
            out.mkdir(parents=True, exist_ok=True)
            out = out / f"{name}.png"
        pb.savev(str(out), "png", [], [])
        print(f"saved {out} ({w}x{h})")

    def run_sequence() -> bool:
        win = app.window
        win.resize(args.width, args.height)
        key = args.run_demo or args.open_demo
        if key and key in demo_jobs:
            job = demo_jobs[key]
            if args.run_demo:
                job.performance.limit_speed, job.performance.speed_limit = True, 3
            app.ctx.publish("edit-job", job)
            if args.advanced:
                win.page("designer").view_switch.set_value("advanced")
                for sec in win.page("designer").sections.values():
                    sec.set_expanded(True)
            if args.run_demo:
                GLib.timeout_add(1200, lambda: app.ctx.publish("action", "start") or False)
        # Park the pointer in a corner so hover effects and tooltips stay out of the shots.
        display = Gdk.Display.get_default()
        seat = display.get_default_seat() if display else None
        if seat is not None and seat.get_pointer() is not None:
            seat.get_pointer().warp(display.get_default_screen(), 1399, 999)

        # Layout switches lower the minimum width; ask again so narrow sizes are reached.
        GLib.timeout_add(400, lambda: win.resize(args.width, args.height) or False)
        GLib.timeout_add(800, lambda: win.resize(args.width, args.height) or False)

        def step(i: int) -> bool:
            if i >= len(pages):
                app.quit()
                return False
            win.show_page(pages[i])
            for act in args.action:
                app.ctx.publish("action", act)

            def snap() -> bool:
                capture(win, pages[i])
                GLib.timeout_add(50, step, i + 1)
                return False

            GLib.timeout_add(args.delay, snap)
            return False

        GLib.timeout_add(args.delay, step, 0)
        return False

    app.connect("activate", lambda *_: GLib.idle_add(run_sequence))
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
