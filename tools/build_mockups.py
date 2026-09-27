#!/usr/bin/env python3
"""Build docs/mockups/index.html from mockups.src.html.

Icons are referenced in the template as ``{{i:<semantic-id>}}`` or
``{{i:<semantic-id>|extra-classes}}``. Every id must exist in
``tools/icons.manifest``; the matching Phosphor SVG is read from the local
asset directory and inlined once as an SVG ``<symbol>`` sprite, so the output
is a single self-contained file with no external references.

``{{LEGEND}}`` is replaced by a generated table of every manifest icon.

Usage:
    python3 tools/build_mockups.py [--icons DIR]
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "tools" / "icons.manifest"
SRC = ROOT / "docs" / "mockups" / "mockups.src.html"
OUT = ROOT / "docs" / "mockups" / "index.html"
DEFAULT_ICON_DIR = Path(
    os.environ.get("LFC_ICON_SRC", "/home/user/projects/assets/Icons/phosphoricons")
)

ICON_RE = re.compile(r"\{\{i:([a-z0-9-]+)(?:\|([^}]*))?\}\}")
SVG_RE = re.compile(r"<svg[^>]*>(.*)</svg>", re.S)


@dataclass(frozen=True)
class IconEntry:
    """One manifest line."""

    semantic_id: str
    phosphor: str
    weight: str
    purpose: str
    group: str

    def source_path(self, icon_dir: Path) -> Path:
        """Return the Phosphor SVG path for this entry's weight."""
        if self.weight == "regular":
            return icon_dir / "regular" / f"{self.phosphor}.svg"
        return icon_dir / self.weight / f"{self.phosphor}-{self.weight}.svg"


def read_manifest(path: Path = MANIFEST) -> dict[str, IconEntry]:
    """Parse the icon manifest into an ordered id -> entry mapping."""
    entries: dict[str, IconEntry] = {}
    group = "misc"
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# ---"):
            group = stripped.strip("# -").strip()
            continue
        if stripped.startswith("#"):
            continue
        parts = stripped.split(None, 3)
        if len(parts) < 3:
            raise ValueError(f"bad manifest line: {line!r}")
        sid, name, weight = parts[:3]
        purpose = parts[3] if len(parts) > 3 else ""
        if sid in entries:
            raise ValueError(f"duplicate icon id: {sid}")
        entries[sid] = IconEntry(sid, name, weight, purpose, group)
    return entries


def symbol_for(entry: IconEntry, icon_dir: Path) -> str:
    """Return an SVG <symbol> element for one icon."""
    svg = entry.source_path(icon_dir).read_text(encoding="utf-8")
    match = SVG_RE.search(svg)
    if not match:
        raise ValueError(f"not an SVG: {entry.source_path(icon_dir)}")
    return f'<symbol id="i-{entry.semantic_id}" viewBox="0 0 256 256">{match.group(1)}</symbol>'


def use_tag(sid: str, classes: str | None) -> str:
    """Return the inline markup that references a sprite symbol."""
    cls = "i" + (f" {classes.strip()}" if classes else "")
    return f'<svg class="{cls}" aria-hidden="true"><use href="#i-{sid}"/></svg>'


def legend(entries: dict[str, IconEntry]) -> str:
    """Render every manifest icon grouped by section."""
    out: list[str] = []
    current = None
    for e in entries.values():
        if e.group != current:
            if current is not None:
                out.append("</div></section>")
            current = e.group
            out.append(f'<section class="lg-group"><h3>{html.escape(e.group)}</h3><div class="lg-grid">')
        out.append(
            '<div class="lg-item">'
            f"{{{{i:{e.semantic_id}|lg-ico}}}}"
            f'<div><code>{e.semantic_id}</code>'
            f"<small>{html.escape(e.phosphor)} · {e.weight}</small>"
            f"<span>{html.escape(e.purpose)}</span></div></div>"
        )
    if current is not None:
        out.append("</div></section>")
    return "".join(out)


def build(icon_dir: Path) -> tuple[int, int]:
    """Render the template. Returns (icons in sprite, bytes written)."""
    entries = read_manifest()
    missing = [e.semantic_id for e in entries.values() if not e.source_path(icon_dir).is_file()]
    if missing:
        raise SystemExit(f"icon files not found in {icon_dir}: {', '.join(missing)}")

    text = SRC.read_text(encoding="utf-8")
    text = text.replace("{{LEGEND}}", legend(entries))

    used: list[str] = []
    unknown: set[str] = set()

    def repl(m: re.Match[str]) -> str:
        sid = m.group(1)
        if sid not in entries:
            unknown.add(sid)
            return ""
        if sid not in used:
            used.append(sid)
        return use_tag(sid, m.group(2))

    text = ICON_RE.sub(repl, text)
    if unknown:
        raise SystemExit(f"icons not in manifest: {', '.join(sorted(unknown))}")

    sprite = (
        '<svg xmlns="http://www.w3.org/2000/svg" style="display:none">'
        + "".join(symbol_for(entries[s], icon_dir) for s in used)
        + "</svg>"
    )
    text = text.replace("{{SPRITE}}", sprite)
    OUT.write_text(text, encoding="utf-8")
    return len(used), len(text.encode())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--icons", type=Path, default=DEFAULT_ICON_DIR, help="Phosphor asset directory")
    args = parser.parse_args(argv)
    count, size = build(args.icons)
    print(f"wrote {OUT.relative_to(ROOT)}: {count} icons, {size / 1024:.1f} KiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
