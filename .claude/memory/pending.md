# Pending Items

- [x] Universal permissions deployed by the user (2026-09-28); .claude/settings.local.json is git-ignored
- [x] Flatpak rsync sha256 filled in after GPG signature verification (2026-09-28)
- [x] dpkg-buildpackage verified 2026-09-28 (153 tests pass during build)
- [ ] flatpak-builder not run (tool and GNOME 47 SDK not installed)
- [ ] rclone/cloud intentionally out of scope (local storage only)
- [x] Coloured status icons in History and Preview
- [ ] Translations beyond the .pot template
- [x] Real desktop verified 2026-09-28: copy to exFAT stick, eject, Quick View progress, tray, close-to-tray
- [x] Drive-connected trigger verified on physical re-plug (2026-09-28), two-way propagated both directions
- [ ] LUKS unlock/lock: not tested (no encrypted drive available)

## Roadmap — Critical Mass & Smart Organization (concept docs; not implemented)
- [ ] **Critical Mass** page: aggressive multi-source capture → type/subtype-sorted copy with duplicate-name handling, end-to-end verification, interruption-tolerant resume, and opt-in verified-move delete. Concept: `docs/CRITICAL_MASS.md`
- [ ] **Persistent Index (near-term, with Critical Mass):** on every run, record each file's original path + source drive, destination path and name-at-destination (incl. `_copy_NN` renames) to a per-run JSONL + master sqlite under `~/.local/share/linfilecopy/index/`. Concept: `docs/INDEX_AND_SMART_ORGANIZATION.md` §2
- [ ] **Smart File Organization (future/advanced):** index-driven re-sort, global dedup, reconstruct-original-view, reversible undo. Doc §3
- [ ] **Smart-Link (future/advanced):** hard-link (same-fs, zero-copy, inode re-designation) / symlink (cross-fs) placement so other apps still reach moved files, with index-maintained self-healing relink; integrates with the verified-move delete (replace source with link). Doc §4, capability-gated
- [ ] **Duplicates (advanced):** point at a folder → tiered stdlib hashing (size→prefix→sha256→byte-verify→inode-collapse, borrowed from LinFileDedup, hashlib-only) with a persistent per-file hash index; reports exact 1-to-1 duplicates AND same-name/different-content name-conflicts (→ `_copy_NN` rename recommendations). All types by default + ignore-type options. NET-NEW large-file time-table/ETA (bytes-weighted throughput) since LinFileDedup projects no time. Reuses ProgressRing; feeds the global Index; backs Critical Mass's dedup pass. Concept: `docs/DUPLICATES.md`
