"""Built-in job templates loaded from ``data/templates/*.json``.

Templates are partial job documents; anything not given uses SyncJob
defaults. ``~`` in paths is expanded to the user's home when instantiated.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from linfilecopy.i18n import _
from linfilecopy.log import get_logger
from linfilecopy.model.job import SyncJob
from linfilecopy.paths import DATA_DIR

_log = get_logger(__name__)
TEMPLATE_DIR = DATA_DIR / "templates"
ORDER = ["backup-documents", "mirror-to-array", "two-way-usb-stick", "snapshot-backup"]
ICONS = {
    "backup-documents": "ep-removable",
    "mirror-to-array": "mode-mirror",
    "two-way-usb-stick": "mode-twoway",
    "snapshot-backup": "feat-snapshots",
}


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    description: str
    icon: str
    data: dict

    def instantiate(self) -> SyncJob:
        """Return a new job (fresh id) built from this template."""
        data = json.loads(json.dumps(self.data))
        for side in ("source", "destination"):
            ep = data.get(side) or {}
            if ep.get("path"):
                ep["path"] = os.path.expanduser(ep["path"])
        job = SyncJob.from_dict(data)
        job.name = _(self.name)
        job.template = self.key
        job.id = ""
        return job.ensure_identity()


def load_templates(directory: Path = TEMPLATE_DIR) -> list[Template]:
    out: list[Template] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _log.warning("skipping template %s: %s", path.name, exc)
            continue
        key = data.get("template") or path.stem
        out.append(Template(key, data.get("name", key), data.get("description", ""), ICONS.get(key, "action-templates"), data))
    out.sort(key=lambda t: ORDER.index(t.key) if t.key in ORDER else len(ORDER))
    return out


def blank_job(preview_first: bool = True) -> SyncJob:
    """A new empty job with safe defaults."""
    job = SyncJob(name=_("New job"), preview_first=preview_first)
    return job.ensure_identity()
