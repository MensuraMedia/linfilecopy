"""Access to the embedded ``lfc-*`` icon set by semantic id.

Semantic ids are defined in ``tools/icons.manifest``; use them everywhere
instead of raw icon names, e.g. ``icon("action-start")``.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

SIZE_BUTTON = 16
SIZE_NAV = 20
SIZE_TILE = 32
SIZE_EMPTY = 64


def icon_name(semantic_id: str) -> str:
    """Return the GTK icon name for a manifest id."""
    return f"lfc-{semantic_id}-symbolic"


def icon(semantic_id: str, pixel_size: int = SIZE_BUTTON) -> Gtk.Image:
    """Create an image for a manifest icon at an exact pixel size."""
    image = Gtk.Image.new_from_icon_name(icon_name(semantic_id), Gtk.IconSize.BUTTON)
    image.set_pixel_size(pixel_size)
    return image


def has_icon(semantic_id: str) -> bool:
    return Gtk.IconTheme.get_default().has_icon(icon_name(semantic_id))


def button(
    semantic_id: str | None,
    label: str | None = None,
    tooltip: str | None = None,
    style: str | None = None,
    flat: bool = False,
) -> Gtk.Button:
    """Build a button with an optional icon and label.

    Icon-only buttons get the tooltip as their accessible name.
    """
    btn = Gtk.Button()
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    if semantic_id:
        box.pack_start(icon(semantic_id), False, False, 0)
    if label:
        lbl = Gtk.Label(label=label, use_underline=True)
        lbl.set_mnemonic_widget(btn)
        box.pack_start(lbl, False, False, 0)
    box.set_halign(Gtk.Align.CENTER)
    btn.add(box)
    if tooltip:
        btn.set_tooltip_text(tooltip)
    if not label and tooltip:
        btn.get_accessible().set_name(tooltip)
        btn.get_style_context().add_class("image-button")
    if style:
        btn.get_style_context().add_class(style)
    if flat:
        btn.set_relief(Gtk.ReliefStyle.NONE)
    return btn
