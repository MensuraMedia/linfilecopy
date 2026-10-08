# Choice controls — separate mutually-exclusive buttons

> Status: **Implemented** · v0.1.0 · 2026-10-08
> How single-choice controls look and behave, and when buttons are grouped vs. separate.
> Code: `ui/components/component_common.py` (`Segmented`), `data/style.css`.

## 1. The rule

A **choice** control — one where picking an option must clear the others — is
drawn as **separate buttons**, not a single joined pill. Selecting one deselects
the rest; exactly one option is always active.

Before, these controls used GTK's `.linked` style, which fuses adjacent buttons
into one pill so they "appear as one button". That read as a single widget rather
than a set of choices, so the default changed to **separate** buttons.

## 2. The `Segmented` widget

`ui/components/component_common.py`:

```python
Segmented(options, active, on_change=None, tooltips=None, linked=False)
```

- A row of `Gtk.ToggleButton`s, each with the `lfc-segment` CSS class.
- **Mutual exclusion** is built in: `_on_toggled` activates the clicked option
  and clears the others, and re-activates the current one if it is clicked again,
  so a choice is never left empty (radio-like, but styled as buttons and
  keyboard/AT accessible via each button's accessible name).
- `value` / `set_value(key, notify=…)` read and set the choice.
- `set_option_sensitive(key, sensitive, tooltip=…)` disables one option with a
  reason (e.g. an option not available for the current filesystem).
- **`linked`** controls *appearance only*:
  - `linked=False` (**default**) — separate buttons with 6px spacing. Use for all
    choices.
  - `linked=True` — the joined-pill look. Not used by current choice controls.

CSS: `button.lfc-segment:checked` paints the active button with the accent
background in both light and dark themes, so the selected choice is obvious
whether the buttons are separate or joined.

## 3. Where it is used (all separate)

| Control | Options |
|---|---|
| Designer view | Simple · Advanced |
| Mode (B2) | Copy · Mirror · Two-way |
| Existing files (B9) | Overwrite · Skip · Overwrite if newer |
| Source contents (B1) | Copy the folder itself · Copy what is inside it |
| Settings theme | System · Light · Dark |
| Scheduler kind | Once · Hourly · Daily · Weekly · Custom · When drive connected |
| Preview filter | All · New · Updated · Deleted · Unchanged |

## 4. What is *not* a choice (stays grouped)

Icon **action toolbars** are grouped with `.linked` for compactness but are **not**
choices — there is nothing to deselect, so the "select one deselects the other"
rule does not apply and they keep the joined look:

- Filter editor: **add / remove / move-up / move-down** (`component_filter_editor.py`).
- File picker: **pick / clear** (`page_designer.py` `_file_button`).

Multi-select chip rows (e.g. the **"Skip these"** exclude presets) are independent
toggles, not a single choice, and are unaffected.

## 5. Guidance for new controls

- "Pick exactly one of N" → `Segmented` (separate buttons, the default).
- "Run one of several actions" → a `.linked` toolbar of `button(...)`s.
- "Turn any number of things on" → independent toggles/chips or `CheckRow`-style
  checkboxes.
