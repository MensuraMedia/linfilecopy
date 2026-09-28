---
date: 2026-09-28
type: fix
files_changed: [linfilecopy/ui/manager_launch.py, linfilecopy/ui/pages/page_designer.py, linfilecopy/ui/pages/page_history.py, linfilecopy/ui/pages/page_dashboard.py, linfilecopy/ui/pages/page_scheduler.py, linfilecopy/ui/pages/page_transfers.py, linfilecopy/ui/manager_drives.py, linfilecopy/app.py, linfilecopy/cli.py, tests/ui_smoke.py]
---

## Change: fixes from an independent review of the UI flows
## Root causes
- Two pages held separate copies of the same job; the Designer saved its stale schedule over the Scheduler's (timer stayed installed). Designer now takes the stored schedule on save and on schedules-changed.
- Path cards committed text only on Enter/focus-out; accelerators don't move focus.
- Run safety logic lived only in the Designer; five other buttons called RunManager.start directly. Centralised in manager_launch.start_interactive.
- Drive actions called on_done before the async refresh completed; the worker now reads the new drive list first.
- Close-to-tray took a GApplication hold that a later real close never released.
- Scheduler replaced its edited object on every reload.
## Testing
All unit tests + tests/ui_smoke.py (2 tests); the regression test fails on the pre-fix code (verified with git stash).
