# Multi-source Copy

> Status: **Implemented** · v0.1.0 · 2026-10-08
> Lets one job copy **several source folders or drives into a single destination**.
> Code: `model/job.py`, `engine/rsync_builder.py`, `engine/planner.py`,
> `model/validation.py`, `ui/components/component_path_card.py`, `ui/pages/page_designer.py`.

## 1. What it does

A source used to be exactly one folder. A job can now have a **primary source**
plus any number of **extra sources** — each its own folder or drive — all copied
into the **one** destination. The destination is always a single folder.

```
/home/sam/Documents ─┐
/home/sam/Pictures  ─┼──►  /media/sam/Backup
/media/sam/USB2/Work ┘
```

rsync copies several sources into one destination natively
(`rsync SRC1 SRC2 SRC3 DEST/`), so this is a thin layer over what rsync already
does for Copy.

## 2. Scope — Copy only (by design)

Multiple sources are allowed for **Copy** only. These stay single-source and are
**blocked with a clear, fixable error** when more than one source is chosen:

| Feature | Why it stays single-source |
|---|---|
| **Mirror** (`--delete`) | "delete anything not in the source" is undefined against a *union* of sources — it would delete files that belong to a different source. |
| **Two-way sync** | Bidirectional reconciliation is defined for one pair of folders; a many-to-one merge has no meaning. |
| **Snapshots / Atomic replace** | Hard-link staging and the `latest` link assume a single source tree. |
| **Parallel streams** | Parallelism already splits one source's top-level entries into buckets. |
| **"Only files listed in" (`--files-from`)** | The file list is relative to one source root. |

The validator produces a blocking `Issue` for each conflict with a fix such as
*"Switch to Copy, or keep a single source for Mirror and Two-way."* The designer
shows these in the usual validation panel and Start stays disabled.

## 3. Model

`SyncJob` (in `model/job.py`):

```python
source: Endpoint                       # the primary source (unchanged)
extra_sources: list[Endpoint] = []     # additional sources (new, additive)

@property
def source_endpoints(self) -> list[Endpoint]:   # primary + non-empty extras, in order
@property
def multi_source(self) -> bool:                 # len(source_endpoints) > 1
```

- **Backward compatible.** `extra_sources` defaults to `[]`; the generic
  (de)serialiser already handles `list[Endpoint]`, so old job JSON loads
  unchanged and **no `schema_version` bump** was needed. Jobs written by older
  app versions simply have no extra sources; jobs with extras opened by an older
  version would ignore them.
- The destination remains a single `Endpoint`.

## 4. rsync command

`engine/rsync_builder.build_rsync_argv(job, source, destination, …)` now accepts
`source: str | Sequence[str]`. Each source gets the same trailing-slash treatment
from the **"copy the folder itself / what is inside it"** toggle, then the single
destination is appended:

```
copy what is inside it →  rsync … /a/ /b/ /c/ /dest/
copy the folder itself →  rsync … /a  /b  /c  /dest/
```

- *Inside it* merges each source's contents into the destination (name
  collisions resolve by the job's overwrite policy, last source wins).
- *The folder itself* places each source as its own subfolder under the
  destination — the usual multi-source intent.

## 5. Planner

`PlanEnv` carries resolved extras (`extra_sources`, `extra_source_exists`) plus
`all_sources` / `source_paths` helpers. In `plan_job`:

- `gather_env` resolves every extra source (UUID → mount point) the same way as
  the primary.
- `_endpoint_issues` reports each extra source that is **missing** (drive not
  connected), **locked**, or **does not exist**, keyed `extra_sources.<i>`.
- `_drive_steps` mounts/unlocks **each** source drive before the copy.
- The plain Copy step builds **one** rsync invocation with all source paths.
- `Plan.source` displays `"<primary> + N more"` in previews and summaries.

The runner is unchanged — it executes the step's argv, which already lists every
source.

## 6. Validation (`model/validation.py`)

For each extra source with a path:
- must be an **absolute** path;
- must not **equal** the destination, nor **contain** it (the copy would include
  itself) — both errors;
- a **warning** if it sits *inside* the destination.

Plus the Copy-only guards in §2 when `job.multi_source` is true.

## 7. UI (`component_path_card.py`, `page_designer.py`)

- The **source** card shows the primary row, an **"Add another source folder"**
  button, and a removable row (`_ExtraSourceRow`: drive picker · path entry ·
  Browse · remove) for each extra source.
- **Drag and drop** several folders at once adds them all — the first fills the
  primary row (if empty), the rest become extra sources.
- The caption shows `"… · +N more source(s)"` when extras are present.
- The **destination** card is unchanged (single folder, no add button).
- Swapping source↔destination keeps the destination single, so it **drops any
  extra sources** (they have nowhere to go on a single destination).

Shared helpers `_fill_drive_popover`, `_choose_folder` and
`_resolve_drive_choice` back both the primary row and every extra row.

## 8. Tests

- `tests/test_rsync_builder.py::test_b1_multi_source_positional_args`
- `tests/test_validation.py` — copy-valid; Mirror/Two-way blocked; snapshot/
  atomic/parallel/files-from blocked; extra-path absolute/overlap checks.
- `tests/test_planner.py` — multi-source command ordering; missing extra reported.
- `tests/test_model.py` — round-trip + helpers; legacy jobs have no extras.

## 9. Known limits / follow-ups

- Quick View and run summaries show the **primary** source path only (a "+N"
  there is a possible polish item).
- **Eject when finished** targets one removable drive (destination, else primary
  source); extra source drives are not auto-ejected.
- Parallel across multiple sources is intentionally out of scope.
- See also the proposed **Critical Mass** capture page (`docs/CRITICAL_MASS.md`),
  which is a larger, catalogued multi-source workflow; this feature is the simple
  "several folders → one destination" case built directly into the Designer.
