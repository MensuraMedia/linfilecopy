# Project: LinFileCopy — CLAUDE.md (v2026.03)

## Overview
Native GTK 3 + Python desktop dashboard for designing, running, monitoring and scheduling
copy/sync jobs between local disks, removable drives and local storage arrays, powered by
rsync. Hard constraints: **no external runtime dependencies**, **local storage only** (no
cloud/SSH), **all icons embedded from the local Phosphor set**.

## Architecture
- Language/Framework: Python 3.10+ · GTK 3.24 via PyGObject · GLib/Gio · UDisks2 over D-Bus
- Engine: system `rsync` (+ `ionice`/`nice`); native two-way sync; inotify via ctypes
- Build system: setuptools (`pyproject.toml`), `glib-compile-resources` for icons/CSS
- Key dependencies: none beyond stdlib + PyGObject (AyatanaAppIndicator3, libsecret optional)
- Layers: `linfilecopy/model` (dataclasses, stores) · `linfilecopy/engine` (no Gtk) · `linfilecopy/ui` (GTK)
- Full design: @docs/CONCEPT.md · UI mockups: `docs/mockups/index.html`

## Build & Test Commands
```
# Vendor icons + compile GResource (after editing tools/icons.manifest or CSS)
python3 tools/vendor_icons.py && tools/build_resources.sh

# Test (model + engine, no display needed)
python3 -m unittest discover -s tests -v

# UI smoke test
xvfb-run -a python3 -m unittest tests.ui_smoke -v

# Run
python3 -m linfilecopy            # GUI
python3 -m linfilecopy run <job>  # headless

# Rebuild mockups
python3 tools/build_mockups.py

# Debian package into releases/ (commit it), install
tools/build_deb.sh
./install.sh            # apt on Debian/Ubuntu; ./install.sh --user elsewhere
```

## Project Conventions
- See @.claude/rules/project-conventions.md (layering, naming, icons, safety defaults)
- Page/widget structure follows mikesdatawork/gtk-python-dashboard-starter:
  `BasePage.build_content()`, `page_*`, `component_*`, `manager_*`, `on_*` handlers
- Commit and push to `origin/main` (github.com/MensuraMedia/linfilecopy) at the end of each phase

## Memory System
This project uses the universal memory management system.
- Session logs: `.claude/memory/sessions/`
- Change manifests: `.claude/memory/changes/`
- Decision log: `.claude/memory/decisions.md`
- Pending items: `.claude/memory/pending.md`
- Memory index: `.claude/memory/MEMORY.md`

## References
- @docs/ for project documentation
- @.claude/rules/ for project rules
- UI theme references: /home/user/projects/-universal-themes/image-reference/
