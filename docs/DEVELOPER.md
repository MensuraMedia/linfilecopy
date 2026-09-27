# Developer guide

## Setup

```sh
sudo apt install python3-gi gir1.2-gtk-3.0 rsync udisks2 xvfb gettext appstream desktop-file-utils
python3 -m linfilecopy          # run from the checkout
```

No virtualenv is needed. There are no pip dependencies, and PyGObject comes from the system.

## Everyday commands

| Task | Command |
|---|---|
| All tests | `python3 -m unittest discover -s tests` |
| One module | `python3 -m unittest tests.test_rsync_builder -v` |
| Screenshot a page headlessly | `xvfb-run -a -s "-screen 0 1400x1000x24" python3 tools/screenshot.py --demo --page designer --out /tmp/d.png` |
| Run a demo job in the GUI and capture it | `… tools/screenshot.py --demo --run-demo docs --page transfers --out /tmp/t.png --delay 2600` |
| Dark mode / narrow | add `--style dark` / `--width 600` |
| Rebuild icons after editing the manifest | `python3 tools/vendor_icons.py` |
| Bundle icons + CSS | `tools/build_resources.sh` |
| App icon | `python3 tools/build_app_icon.py` |
| Mockups | `python3 tools/build_mockups.py` |
| Translation template | `tools/update_pot.sh` then `tools/build_mo.sh` |
| Validate packaging | `desktop-file-validate packaging/*.desktop && appstreamcli validate packaging/*.metainfo.xml` |

## Rules (enforced by tests)

1. `model/` and `engine/` never import Gtk or Gdk. The UI receives engine events only through `GLib.idle_add`.
2. Only standard-library and `gi` imports are allowed. Never use `shell=True`, and never import network modules.
3. Every rsync flag is produced in `engine/rsync_builder.py` and has a golden test.
4. Icons come only from `tools/icons.manifest` (the local Phosphor set). Use `icon("semantic-id")`.
5. Never assign to `_` in a function that calls `_()`. Doing so makes `_` a local name and
   crashes at runtime; `tools/check_gettext_shadow.py` catches it.
6. Nothing slow may run on the main thread: subprocesses, directory walks and D-Bus calls
   all happen on worker threads.

## Adding a feature option

1. Add the field to the right option dataclass in `model/job.py`, with a safe default. Old job files load unchanged.
2. Add structural checks to `model/validation.py` and environment checks to `engine/planner.py`.
3. Map it to rsync in `engine/rsync_builder.py` and add a golden test in `tests/test_rsync_builder.py`.
4. Add a control in `ui/pages/page_designer.py` with `_bind_switch`, `_bind_spin` or `_bind_combo`. The live preview updates automatically.
5. If it needs an icon, add it to `tools/icons.manifest` and run `tools/vendor_icons.py`.

## Adding a page

Follow the starter-repo pattern:

```python
class ReportsPage(BasePage):
    page_id = "reports"
    title = _("Reports")

    def build_content(self) -> None:
        self.add_title(self.title)
```

Register it in `ui/pages/__init__.py` and `ui/sidebar.py` (`NAV_ITEMS`), and add `nav-reports`
and `nav-reports-active` to the icon manifest.

## Project process

This repository follows the universal instruction set:
- Record every change in `changelog.md`.
- Write a change manifest per feature in `.claude/memory/changes/`.
- Log decisions in `.claude/memory/decisions.md`.
- Commit and push to `origin/main` at the end of each phase.
