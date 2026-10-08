# MEMORY.md — Project Memory Index
# Keep under 200 lines. One entry per line. Link to detail files.

## Session Logs
<!-- Add newest first -->
- [2026-10-08 separate buttons + multi-source](sessions/2026-10-08_separate-buttons-multi-source.md) — menu launcher, installer refresh, two Designer features shipped
- [2026-10-05 Capture & Organize concepts](sessions/2026-10-05_capture-organize-concepts.md) — 5 concept docs + progress ring; handoff written
- [2026-09-27 initial build](sessions/2026-09-27_2340_initial-build.md) — concept → v0.1.0 in one session

## Shipped feature docs (implemented)
- Multi-source Copy: `docs/MULTI_SOURCE.md` (SyncJob.extra_sources[]; Copy-only; several folders → one destination)
- Choice controls / separate buttons: `docs/UI_CONTROLS.md` (Segmented linked=False default)

## Design concepts (proposed, not implemented)
- Handoff / pick-up guide: `docs/HANDOFF.md`
- Capture & Organize suite: `docs/CRITICAL_MASS.md`, `docs/CRITICAL_MASS_PROMPT_RULES.md`, `docs/DUPLICATES.md`, `docs/INDEX_AND_SMART_ORGANIZATION.md` · roadmap in `pending.md`

## Changes
<!-- Add newest first -->
- [Separate buttons + multi-source Copy](changes/2026-10-08_separate-buttons-multi-source.md)
- [Active-Transfers progress ring](changes/2026-10-02_transfers-progress-ring.md)
- [UI review fixes](changes/2026-09-28_ui-review-fixes.md)
- [Data-safety fixes](changes/2026-09-28_data-safety-fixes.md)
- [P7–P9 triggers, polish, packaging](changes/2026-09-28_p7-p9-triggers-polish-packaging.md)
- [P3/P6 runner + strategies](changes/2026-09-27_p3-runner-strategies.md)
- [P2 drives + builder](changes/2026-09-27_p2-drives-builder.md)
- [P1 model](changes/2026-09-27_p1-model.md)
- [P0 foundation](changes/2026-09-27_p0-foundation.md)

## Decisions
- [Decision Log](decisions.md) — Architectural and design decisions

## Project Context
- LinFileCopy: GTK3/Python rsync dashboard, local drives only; design in docs/CONCEPT.md; repo github.com/MensuraMedia/linfilecopy
- Reference: gtk-python-dashboard-starter (structure), -universal-instruction-set (process), -universal-themes (UI refs)

## Feedback & Preferences
- No external runtime deps; icons only from /home/user/projects/assets/Icons/phosphoricons (mandatory)
- No cloud/network storage in this environment
- Keep git updated with docs and components (commit + push per phase)
