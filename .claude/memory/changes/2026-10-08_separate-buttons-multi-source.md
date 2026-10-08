# Change manifest — separate choice buttons + multi-source Copy

- **Date:** 2026-10-08
- **Features:** (1) segmented choice controls render as separate mutually-exclusive
  buttons; (2) a source can be several folders/drives into one destination.
- **Requested by:** user — "no multi-button buttons … make them 2 buttons with a
  rule that if one is selected the other cannot"; and "allow multi folder and/or
  multi drive selection … as a source; as long as the destination is a single
  destination."

## 1. Separate choice buttons
The `Segmented` widget already enforced single-choice (radio-like). It defaulted
to the GTK `.linked` style, which joins the buttons into one pill ("appear as one
button"). Flipped the default so choices draw as distinct buttons.

- `ui/components/component_common.py`: `Segmented.__init__` default `linked=True`
  → `linked=False`. No logic change — mutual exclusion was already there
  (`_on_toggled` re-activates the clicked one and clears the rest). CSS already
  styles `button.lfc-segment:checked`, so separate buttons show the accent.
- Affects all 7 segmented controls: Simple/Advanced, Copy·Mirror·Two-way,
  Overwrite/Skip/Overwrite-if-newer, copy-folder-itself/contents, settings theme,
  scheduler kind, preview-dialog filter.
- Action **toolbars** that also use `.linked` (filter add/remove/up/down in
  `component_filter_editor.py`, the pick/clear file button in `page_designer.py`)
  are NOT choices, so they were left joined — the "select one deselects the other"
  rule does not apply to them.

## 2. Multi-source Copy
Design decision: **multiple sources are supported in Copy only.** Mirror,
Two-way, snapshots, atomic replace, parallel streams and "only files listed in"
are single-source by nature; choosing more than one source with any of them is a
blocking validation error with a clear fix. Destination is always single.

- `model/job.py`: new field `extra_sources: list[Endpoint]` (additive, default
  `[]`, generic (de)serialiser already handles `list[Endpoint]`, no schema bump).
  Helpers `SyncJob.source_endpoints` (primary + non-empty extras) and
  `SyncJob.multi_source`.
- `engine/rsync_builder.py`: `build_rsync_argv(source=...)` now accepts
  `str | Sequence[str]`; emits one positional arg per source (each gets the
  trailing-slash / no-slash treatment from copy_contents) before the destination.
- `model/validation.py`: per-extra-source checks (absolute path; not equal to /
  not containing the destination; warn if inside it) and the multi-source guards
  above (mode must be Copy; no snapshots/atomic/parallel/files_from).
- `engine/planner.py`: `PlanEnv` gains `extra_sources` (resolved) +
  `extra_source_exists`, plus `all_sources`/`source_paths`. `gather_env` resolves
  every extra source; `_endpoint_issues` reports each missing/locked/nonexistent
  extra; `_drive_steps` mounts/unlocks each source drive; the plain Copy step
  builds one rsync with all source paths; `Plan.source` shows "… + N more".
  (The runner just executes the step argv, so it needed no change.)
- UI `ui/components/component_path_card.py`: refactored. Shared module helpers
  `_fill_drive_popover`, `_choose_folder`, `_resolve_drive_choice`. New
  `_ExtraSourceRow` (drive picker + path + browse + remove). The source
  `PathCardWidget` gains an "Add another source folder" button + an extras
  container; `extra_endpoints` exposes them; drag-drop of several folders adds
  them all (primary first, then extras). Destination card is unchanged (single).
- `ui/pages/page_designer.py`: `_on_source_changed` writes `job.extra_sources`;
  `_populate` uses `set_sources(...)`; Swap clears extras (destination is single).

## Files affected
- `linfilecopy/model/job.py`, `linfilecopy/model/validation.py`
- `linfilecopy/engine/rsync_builder.py`, `linfilecopy/engine/planner.py`
- `linfilecopy/ui/components/component_common.py`
- `linfilecopy/ui/components/component_path_card.py`
- `linfilecopy/ui/pages/page_designer.py`
- Docs: `README.md`, `docs/CONCEPT.md`, `changelog.md`, `.claude/memory/decisions.md`
- Tests: `tests/test_rsync_builder.py`, `tests/test_validation.py`,
  `tests/test_planner.py`, `tests/test_model.py`

## Tests / verification
- `python3 -m unittest discover -s tests` → **157 passed** (9 new: builder
  positional args, validation copy-valid + mirror/two-way/snapshot/atomic/
  parallel/files_from guards + extra-path/overlap, planner multi-source command +
  missing-extra, model round-trip + legacy-no-extras).
- `tests.ui_smoke` → OK (all 7 pages build).
- Live render `tools/screenshot.py --page designer --demo`: choices show as
  separate accent-selected buttons; "Add another source folder" present under the
  source row; destination single.

## Notes / follow-ups
- Quick View / run summaries still show the primary source path only; a "+N"
  there is a possible polish item.
- Eject-after still targets one removable drive (destination, else primary source);
  extra source drives are not auto-ejected.
- Parallel streams across multiple sources is intentionally out of scope (blocked).
