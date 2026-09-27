#!/usr/bin/env python3
"""Print the GResource XML listing every vendored icon and stylesheet."""
from __future__ import annotations

from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "linfilecopy" / "data"
PREFIX = "/io/github/mensuramedia/LinFileCopy"


def main() -> None:
    files = sorted(p.relative_to(DATA).as_posix() for p in (DATA / "icons").rglob("*.svg"))
    files += sorted(p.relative_to(DATA).as_posix() for p in DATA.glob("*.css"))
    print('<?xml version="1.0" encoding="UTF-8"?>')
    print("<gresources>")
    print(f'  <gresource prefix="{PREFIX}">')
    for f in files:
        attr = ""
        print(f"    <file{attr}>{f}</file>")
    print("  </gresource>")
    print("</gresources>")


if __name__ == "__main__":
    main()
