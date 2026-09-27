---
date: 2026-09-27
type: feature
files_changed: [linfilecopy/engine/filesystems.py, linfilecopy/engine/drives.py, linfilecopy/engine/rsync_builder.py, linfilecopy/engine/planner.py, linfilecopy/model/job.py, tests/test_rsync_builder.py, tests/test_drives.py, tests/test_planner.py, tests/fixtures_udisks.py]
---

## Change: P2 drives, filesystem adaptation, rsync builder, planner
## Why
Phase P2 (CONCEPT §5). The builder is the single source of every rsync flag; the planner turns job + environment into steps and the preview text.
## Impact
Endpoint gained `container_uuid` (LUKS). exFAT/FAT/NTFS limits are applied automatically and reported as an "Adjusted for …" issue. rsync output formats verified against rsync 3.2.7 (preview `%i %l %n%L`, `*deleting   0 path`, progress2 `\r` segments).
## Testing
94 tests; live UDisks2 listing verified on this machine (2 NVMe + exFAT USB stick).
