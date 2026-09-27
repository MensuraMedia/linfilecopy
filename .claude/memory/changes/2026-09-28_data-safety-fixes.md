---
date: 2026-09-28
type: fix
files_changed: [linfilecopy/model/validation.py, linfilecopy/engine/twoway.py, linfilecopy/engine/parallel.py, linfilecopy/engine/planner.py, linfilecopy/engine/snapshots.py, linfilecopy/engine/atomic.py, linfilecopy/engine/runner.py, tests/test_validation.py, tests/test_planner.py, tests/test_integration_runner.py]
---

## Change: data-safety fixes from an independent review of the engine
## Root causes
1. Validation only checked destination-inside-source; source-inside-destination let Mirror delete the source.
2. Parallel mode replaced the user's files-from list with its buckets and ran an unrestricted delete pass.
3. Two-way scan swallowed os.walk/lstat errors, so unreadable items looked deleted and were trashed on the other side.
4. Parallel buckets always resolved names inside the source, ignoring "copy the folder itself".
5. rsync treats files-from lines starting with # or ; as comments even with --from0 (verified); lists now NUL-separated AND "./"-prefixed. The reviewer's suggested fix (--from0 alone) was insufficient — caught by a regression test.
6. Folder deletions renamed a now-empty dir onto an existing trash path (ENOTEMPTY); trash stamps had 1 s resolution and os.rename overwrote.
7. Two-way re-created a missing destination and treated its absence as mass deletion.
8. Snapshot folders carried their final name while being written; retention kept the newest (partial) one.
9. Atomic fallback had no rollback. 10. Post steps (lock) were skipped on cancel.
## Testing
153 tests, including new regression tests for each confirmed finding.
