# LinFileCopy — Architecture (as built)

The design rationale is in [CONCEPT.md](CONCEPT.md). This document describes the code as it
exists and where it differs from the concept.

## Layers

```
linfilecopy/
├── model/    SyncJob and friends, validation, cron, templates, JobStore, HistoryStore   (no GTK)
├── engine/   tools, drives (UDisks2), filesystems, rsync_builder, planner, runner,
│             progress, exitcodes, snapshots, atomic, parallel, filtermatch, twoway,
│             watcher (inotify), scheduler (systemd/cron)                                (no GTK)
├── ui/       window, sidebar, pages/page_*, components/component_*, manager_* services
├── app.py    Gtk.Application: startup, services, actions, tray/close behaviour
└── cli.py    headless run / preview / list / validate
```

`tests/test_code_rules.py` enforces the layering: model and engine never import Gtk or
Gdk, only standard-library and `gi` imports are allowed anywhere, there is no
`shell=True`, and every icon used in the UI must exist in `tools/icons.manifest`.

## Flow of a run

```
Designer ──(SyncJob)──▶ RunManager.start ──▶ JobRun thread
   ▲                                              │ gather_env: UDisks2 drives, fs type, tools
   │                                              │ plan_job  → Plan(steps, issues)
   │ GLib.idle_add                                │ UNLOCK/MOUNT → re-plan
   └──────── ctx.publish("run-updated") ◀─────────┤ RSYNC / PARALLEL / TWOWAY / strategy steps
                                                  │ UNMOUNT / LOCK / POWER_OFF
                                                  ▼
                                   HistoryStore + run log + notification
```

- The **planner is pure**. Everything it needs about the system comes in a `PlanEnv`, so the
  designer, the runner and the CLI all produce the same plan. The designer re-plans 250 ms
  after any change, on a worker thread.
- **`rsync_builder` is the only place** where rsync flags are decided. It has golden tests for
  every feature and every filesystem type.
- The **runner** starts rsync in its own session (`start_new_session=True`). Pause, resume
  and cancel signal the whole process group. Several processes can be active at once
  (parallel mode), and their progress is combined into a single reading.
- **Two-way sync** (`twoway.py`) is a pure `decide()` function over three trees (A, B and the
  last-synced state), plus an apply step. The apply step moves files to `.lfc-trash` and copies
  the decided paths with `rsync --files-from --ignore-times`.

## UI conventions

The UI follows `mikesdatawork/gtk-python-dashboard-starter`: a `NavigationManager`,
`BasePage.build_content()`, and role-prefixed modules (`page_*`, `component_*`, `manager_*`).
It departs from the starter in three ways:
- It uses `Gtk.Application` and a `HeaderBar`, which are needed for actions, notifications and single-instance behaviour.
- Imports are package-relative.
- Theme accents come from settings instead of hard-coded themes.

Pages communicate only through `AppContext.publish/subscribe` on the main thread. Engine
callbacks from worker threads are marshalled with `GLib.idle_add`.

## Differences from the concept

| Concept | As built | Why |
|---|---|---|
| P6 strategies after the MVP UI | Built together with the runner (P3) | The runner dispatches to them; end-to-end tests cover them together |
| Retention: newest per day / week | Also keeps everything from the last 24 h | Running twice in a day must not delete the earlier snapshot |
| Parallel mirror | Extra delete-only rsync pass | `--delete` inside a `--files-from` run cannot see top-level extras |
| Two-way preview shows argv | Shows a plan description | The file lists are decided at run time from the scan |
| Files counter "N of M" | "N copied · X of Y checked" | rsync's total counts folders as well as files |
| Flatpak rsync checksum | Taken from a download whose GPG signature was verified | Never ship an unverified checksum |

## Tests

`python3 -m unittest discover -s tests` runs 160+ tests in about 15 seconds. They include:
- end-to-end runs with the real rsync on temporary folders (copy, preview, mirror, pause and
  resume, cancel, snapshots, atomic replace, parallel, two-way, queueing)
- a check that the filter matcher gives the same result as `rsync --list-only`
- scheduler backends tested with a fake systemctl and crontab

UI smoke test: `xvfb-run -a python3 tools/screenshot.py --demo --page dashboard --out /tmp/x.png`.
