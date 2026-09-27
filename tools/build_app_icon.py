#!/usr/bin/env python3
"""Compose the application icon from the vendored Phosphor glyphs and export PNGs.

Output:
  linfilecopy/data/app-icon/io.github.mensuramedia.LinFileCopy.svg
  linfilecopy/data/app-icon/hicolor/<N>x<N>/apps/io.github.mensuramedia.LinFileCopy.png
  linfilecopy/data/app-icon/io.github.mensuramedia.LinFileCopy-symbolic.svg (monochrome, for panels)

The tile is a rounded square in the default accent blue with a white Phosphor
"copy" glyph and a sync badge ("arrows-clockwise"), matching the in-app icons.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "linfilecopy" / "data" / "icons" / "hicolor" / "scalable" / "actions"
OUT = ROOT / "linfilecopy" / "data" / "app-icon"
APP_ID = "io.github.mensuramedia.LinFileCopy"
SIZES = [16, 24, 32, 48, 64, 128, 256, 512]


def inner(name: str) -> str:
    svg = (ICONS / f"lfc-{name}-symbolic.svg").read_text(encoding="utf-8")
    return re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)  # type: ignore[union-attr]


def build_svg() -> str:
    glyph, badge = inner("app-glyph"), inner("app-badge")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="tile" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#4a92ea"/>
      <stop offset="1" stop-color="#1c63c4"/>
    </linearGradient>
  </defs>
  <rect x="16" y="20" width="224" height="224" rx="52" fill="#15487f" opacity="0.35"/>
  <rect x="16" y="12" width="224" height="224" rx="52" fill="url(#tile)"/>
  <g transform="translate(46 40) scale(0.62)" fill="#ffffff">{glyph}</g>
  <circle cx="186" cy="182" r="46" fill="#ffffff"/>
  <g transform="translate(158 154) scale(0.22)" fill="#1c63c4">{badge}</g>
</svg>
"""


def build_symbolic() -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 256 256" fill="#2e3436">'
            f"{inner('app-glyph')}</svg>\n")


def main() -> int:
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    OUT.mkdir(parents=True, exist_ok=True)
    svg_path = OUT / f"{APP_ID}.svg"
    svg_path.write_text(build_svg(), encoding="utf-8")
    (OUT / f"{APP_ID}-symbolic.svg").write_text(build_symbolic(), encoding="utf-8")
    for n in SIZES:
        target = OUT / "hicolor" / f"{n}x{n}" / "apps" / f"{APP_ID}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        GdkPixbuf.Pixbuf.new_from_file_at_size(str(svg_path), n, n).savev(str(target), "png", [], [])
    print(f"wrote {svg_path.relative_to(ROOT)} and {len(SIZES)} PNG sizes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
