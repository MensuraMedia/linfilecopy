---
date: 2026-09-27
type: feature
files_changed: [linfilecopy/engine/progress.py, linfilecopy/engine/exitcodes.py, linfilecopy/engine/runner.py, linfilecopy/engine/snapshots.py, linfilecopy/engine/atomic.py, linfilecopy/engine/parallel.py, linfilecopy/engine/filtermatch.py, linfilecopy/engine/twoway.py, tests/test_integration_runner.py, tests/test_progress.py, tests/test_snapshots.py, tests/test_twoway_decide.py, tests/test_filtermatch.py]
---

## Change: P3 runner and progress; P6 strategies (pulled forward)
Strategies were implemented together with the runner because the runner dispatches to them and integration tests exercise them end to end.

## Bugs found and root causes
- Snapshot run failed with rsync code 11: rsync creates only the final path component; the snapshot root did not exist. Runner now creates the target's parent when the grandparent exists (never creates a missing mount point).
- Two-way could skip decided copies: rsync's default quick check compares whole seconds; two-way transfers now pass --ignore-times.
- Two-way preview listed a conflict twice (as UPDATE and CONFLICT).
- ResourceWarning: rsync stdout/stderr pipes were not closed.
- Retention removed same-day snapshots; policy now keeps everything from the last 24 h plus daily/weekly.

## Testing
128 tests, including 13 end-to-end runs with real rsync (copy, preview, mirror, pause/resume/cancel, snapshots with shared inodes, atomic swap, parallel mirror, two-way merge/propagate/trash/keep-both/ask/guard, queueing).
