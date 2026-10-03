# Change manifest — Active Transfers progress ring

- **Date:** 2026-10-02
- **Feature:** Circular percentage progress indicator on the Active Transfers page
- **Requested by:** user (wanted a LinFileDedup-style % ring shown next to each
  copy/mirror/sync job on the Active page, reduced in size)

## What changed
Added a compact circular progress ring to each run card on the Active Transfers
page, beside the existing linear progress bar.

- New widget `ProgressRing(Gtk.DrawingArea)` in
  `linfilecopy/ui/components/component_run_card.py`, built the same way as the
  existing `Sparkline` (Cairo `draw` handler, theme colours via
  `style_context.lookup_color`).
  - Dim track (`lfc_trough`) + status-coloured progress arc with round caps and
    a top→bottom-right two-tone gradient (base colour lightened 28%).
  - Centred bold percentage text in the theme foreground colour.
  - Indeterminate mode: a ~100° arc rotates (~30 fps GLib timeout) while the run
    is RUNNING with no percentage yet, mirroring `Gtk.ProgressBar.pulse()`.
    Animation timer starts on map / stops on unmap/destroy (no leak).
- Colour by status (reuses the card's existing `kind`): running→`lfc_accent`,
  success→`lfc_ok`, failed→`lfc_err`, warning→`lfc_warn`, paused/queued/
  waiting/cancelled→`lfc_dim`.
- Layout: `self.bar` is now wrapped with the ring in a horizontal `prog_row`
  (`ring` fixed 50px, bar expands), vertically centred.
- `RunCardWidget.update()` sets the ring from `run.snapshot` (`.fraction`,
  `.percent`) right after it sets the bar, so both stay in lock-step.

## Files affected
- `linfilecopy/ui/components/component_run_card.py` (new `ProgressRing`, `_blend`
  helper, imports `math`/`cairo`/`GLib`, layout + `update()` wiring)
- `changelog.md`, `.claude/memory/decisions.md` (recorded)

## Tests / verification
- `python3 -m unittest discover -s tests` → 157 passed (unchanged).
- Rendered on the live display with `tools/screenshot.py --demo --run-demo docs
  --page transfers`: ring shows blue 37% while running and green 100% on
  completion, matching the bar.

## Notes / follow-ups
- Default arc colour follows the app accent (blue), not LinFileDedup's red→orange;
  swapping to a warm pair is a one-line change in `ProgressRing._arc`.
- No new user-visible strings except `_("Progress")` (accessible name);
  `component_run_card.py` is already in `po/POTFILES.in`.
- The ring and the linear bar are intentionally both shown (glance + precise);
  if redundancy is unwanted, the bar could later be dropped on narrow widths.
