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

    from linfilecopy.app import LinFileCopyApp
    from linfilecopy.model.settings import AppSettings

    settings = AppSettings(style=args.style)
    settings.save()
    if args.demo:
        from tools.demo_data import seed

        seed()

    pages = args.page or ["dashboard"]
    app = LinFileCopyApp()

    def capture(win: Gtk.Window, name: str) -> None:
        gdk_win = win.get_window()
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
