---
paths:
  - "**/*"
---

# LinFileCopy Project Rules

1. **No external runtime dependencies.** Python stdlib + PyGObject (GTK 3, GLib/Gio) + system tools (rsync, ionice, UDisks2 over D-Bus) only. No pip runtime packages, no network assets.
2. **Local storage only.** No cloud, rclone, SSH or network code paths.
3. **Icons**: only from `tools/icons.manifest` (local Phosphor set). Add new icons there, run `python3 tools/vendor_icons.py`, reference by semantic id via `ui/icons.py`.
4. **Layering**: `linfilecopy/model` and `linfilecopy/engine` MUST NOT import Gtk/Gdk. UI receives engine events only through `GLib.idle_add`.
5. **Never block the GTK main loop**: subprocesses, scans, UDisks calls run on worker threads or Gio async.
6. **Every rsync flag** comes from `engine/rsync_builder.py` and has a golden test in `tests/test_rsync_builder.py`.
7. **Naming** (from gtk-python-dashboard-starter): pages `page_*.py` → `*Page(BasePage)` implementing `build_content()`; widgets `component_*.py` → `*Widget`; controllers `manager_*.py` → `*Manager`; handlers `on_*`.
8. **Style**: full type hints, module + public docstrings, user-visible strings wrapped in `_()`.
9. **Safety defaults**: preview-first on, confirm deletes, two-way uses `.lfc-trash`.
10. Update `changelog.md` with every change (ISO 8601), write a change manifest for each feature, record decisions in `.claude/memory/decisions.md`.
