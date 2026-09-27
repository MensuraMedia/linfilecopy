"""gettext setup. Import ``_`` and ``ngettext`` from here for every user-visible string."""
from __future__ import annotations

import gettext
from pathlib import Path

DOMAIN = "linfilecopy"
_LOCALE_DIR = Path(__file__).resolve().parent / "data" / "locale"

_translation = gettext.translation(DOMAIN, localedir=str(_LOCALE_DIR), fallback=True)
_ = _translation.gettext
ngettext = _translation.ngettext

__all__ = ["DOMAIN", "_", "ngettext"]
