---
date: 2026-09-28
type: feature
files_changed: [linfilecopy/engine/watcher.py, linfilecopy/ui/manager_triggers.py, linfilecopy/ui/manager_tray.py, linfilecopy/app.py, linfilecopy/resources.py, linfilecopy/ui/window.py, linfilecopy/ui/components/component_run_card.py, linfilecopy/ui/pages/page_base.py, linfilecopy/ui/pages/page_designer.py, linfilecopy/engine/scheduler.py, linfilecopy/engine/progress.py, tools/build_app_icon.py, tools/update_pot.sh, tools/build_mo.sh, tools/demo_data.py, tools/screenshot.py, packaging/*, po/*, docs/*, README.md, tests/test_watcher.py]
---

## Change: triggers, tray, app icon, responsiveness, packaging, documentation
## Bugs found and root causes
- Notification crash: PyGObject exposes no `set_default_action_and_target_value`; switched to detailed action strings `app.show-run('id')`.
- Window could not shrink below ~1100 px: GTK clamps to the minimum of the *current* layout, and the side-by-side designer needed 716 px; horizontal AUTOMATIC scrolling on page scrollers removes the hard minimum so layout switches can happen.
- Header minimum 645 px from long job titles: title/subtitle now ellipsize.
- Sidebar toggle had no icon: its child was excluded from show_all by set_no_show_all on the button.
- Preview listed the transfer root "./" as a change.
- Flatpak manifest: a guessed sha256 was written and then replaced by an explicit FILL-IN placeholder (never ship unverified checksums).
## Testing
143 tests pass. GUI verified headlessly: real job run through Start → live card; preview dialog; dark mode; 600/800 px layouts. `desktop-file-validate` and `appstreamcli validate` pass. dpkg-buildpackage and flatpak-builder not run (dh-python / flatpak-builder not installed here).
