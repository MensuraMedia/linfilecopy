# Project Change Log

> Local record of all changes. Does NOT depend on git. Updated every time a change is made.

| Date-Time | Change Description |
|-----------|-------------------|
| 2026-09-27T17:40 | Created docs/CONCEPT.md v0.1, tools/icons.manifest, tools/build_mockups.py, docs/mockups (10 screens); git init + remote MensuraMedia/linfilecopy |
| 2026-09-27T18:20 | CONCEPT v0.2: scope restricted to local/attached storage; removed cloud/rclone/SSH; redefined #6 #10 #13 #20, dropped #9; mockups + manifest updated |
| 2026-09-27T18:45 | Applied universal standards: .claude/ rules, memory, agents (5), skills (3), roles (2), board; CLAUDE.md; .claudeignore; changelog.md |
| 2026-09-27T19:05 | P0 foundation: package skeleton, paths/i18n/logging, icon vendoring (114 icons) + GResource with source fallback, light/dark CSS + accent, ThemeManager (portal-aware), sidebar/window/BasePage shell, app actions + accelerators, shortcuts window, tool detection, screenshot tool, pyproject, 11 tests |
| 2026-09-27T19:40 | P1 model: enums, SyncJob (all features, tolerant JSON, v1 migration), cron parser/next-run, structural validation with fixes, 4 JSON templates, JobStore (atomic writes, id checks), HistoryStore (sqlite, parameterised); 48 tests |
| 2026-09-27T20:30 | P2 drives + builder: filesystems capability table + mountinfo, UDisks2 parsing/client (UUID endpoints, LUKS, RAID, eject), pure rsync_builder (every flag), planner (steps: unlock/mount/rsync/snapshot/atomic/parallel/two-way/unmount/lock/power-off; env issues incl. fs adjustments); Endpoint.container_uuid; 94 tests |
| 2026-09-27T21:40 | P3 runner + P6 strategies: progress/preview/stats parsers (fixtures from rsync 3.2.7), exit-code explanations with stderr refinement, JobRun (process group pause/resume/cancel, retries with backoff, logs, history, drive steps with re-plan), RunManager (same-destination queue), snapshots (latest link, 24h+daily+weekly retention), atomic (hard-link clone + renameat2 exchange), parallel (balanced buckets + mirror delete pass), rsync-compatible filter matcher (verified against rsync), native two-way sync (state, conflicts, trash, delete guard); 128 tests |
| 2026-09-27T21:40 | Fixes found by integration tests: snapshot root not created (rsync only makes last level); two-way copies need --ignore-times (rsync whole-second quick check); conflict rows listed twice in preview; rsync pipes not closed; retention kept only one snapshot per day (now keeps last 24 h) |
