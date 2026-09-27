---
date: 2026-09-27
type: feature
files_changed: [pyproject.toml, linfilecopy/__init__.py, linfilecopy/__main__.py, linfilecopy/app.py, linfilecopy/cli.py, linfilecopy/paths.py, linfilecopy/i18n.py, linfilecopy/log.py, linfilecopy/formatting.py, linfilecopy/resources.py, linfilecopy/engine/tools.py, linfilecopy/model/settings.py, linfilecopy/ui/*, linfilecopy/data/*, tools/vendor_icons.py, tools/build_resources.sh, tools/gen_gresource_xml.py, tools/screenshot.py, tests/test_tools.py, tests/test_settings.py]
---

## Change: P0 foundation
Application shell (Gtk.Application + HeaderBar + sidebar + stack), embedded icon pipeline, theming, tool detection.

## Why
First phase of docs/CONCEPT.md §5.

## Impact
All later pages build on BasePage, component_common and AppContext.

## Testing
11 unit tests; headless screenshots (light 1180px, dark 800px compact) under xvfb verified icons, CSS tokens and responsive sidebar.
Root cause of one bug fixed on the way: a stale compiled gresource shadowed newer CSS and `load_from_resource` only warns; now bundle staleness is checked and resource existence probed first.
