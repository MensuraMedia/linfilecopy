# File Index & Smart File Organization — Advanced Technical Concept

> Status: **Proposed (advanced / future)** · Concept version 0.1 · 2026-10-03
> Builds on: [CRITICAL_MASS.md](CRITICAL_MASS.md) · Parent design: [CONCEPT.md](CONCEPT.md)
> Scope: a **persistent, cross-run index** that Critical Mass writes on every run (original
> path ⇄ destination path, including any `_copy_NN` rename), and the **Smart File Organization**
> feature it later powers — including **hard-link / symlink ("smart-link") re-designation** so
> other applications keep reaching a file after it has been moved or reorganised.
> Constraints unchanged: **local storage only, no external runtime deps, engine never imports
> Gtk, stdlib + system tools only.**

---

## 1. Summary and relationship to Critical Mass

Critical Mass (CRITICAL_MASS.md) already writes a per-destination `_catalog/` that is
**operational** state for one run: it drives copy/verify/resume/delete and lives next to the
files it placed. This document adds two things layered **above** that:

1. **The Index** — a **persistent, append-only, global** record, separate from any single
   destination and surviving every run. On **every Critical Mass run** it records, for **every
   file it touched**, the **original absolute path** (and source drive identity), the
   **destination location**, and the **name at the destination — even when the file was renamed
   as a duplicate** (`MyFile_copy_01.txt`). It is the long-term memory of "where did this come
   from, and where is it now."
2. **Smart File Organization** — a future feature that uses the Index to reorganise,
   consolidate, de-duplicate and *reconstruct* file layouts **without losing provenance or
   breaking other applications**, because the Index knows every file's history and current
   location, and because moves can leave an **index-maintained link** behind at the old path.

The Index is the enabling substrate; Smart Organization and Smart-Link are what it unlocks.

## 2. The persistent Index

### 2.1 What it records

One **file placement** record per file, per run (the unit of truth):

| Field | Meaning |
|---|---|
| `run_id` | The Critical Mass run that produced this placement (FK to a run record). |
| `sha256` | Content hash — the **stable identity** of the file across renames and moves. |
| `size`, `mtime` | From the source at capture time. |
| `origin_path` | The file's **original absolute path** on its source. |
| `origin_drive_uuid`, `origin_label` | Which drive/volume it came from (identity survives remounts). |
| `category`, `subtype` | The taxonomy bucket it was sorted into. |
| `dest_root` | The destination root of that run. |
| `dest_path` | The **final** path at the destination, **including any `_copy_NN` rename**. |
| `dest_name` | The leaf name actually written (so a rename is first-class, not inferred). |
| `action` | `copied` · `skipped-identical` (points at the pre-existing twin) · `kept-both` · `renamed` · `moved` (verified-move delete) · `linked` (§4). |
| `link_kind`, `link_path` | If a link was left behind (§4): `hardlink`/`symlink` and where. |
| `verified_at` | When the copy was confirmed (from the run's catalog). |
| `event_ts` | When this placement/record was written. |

A **run record** carries: `run_id`, timestamp, the source list, destination, the options used
(organisation, dedup, verification level, after-verify action), and totals.

### 2.2 Per-run individual index + master DB

Both, by design:

- **Per-run individual index** — each run writes its own immutable snapshot,
  `index/runs/<run_id>.jsonl` (one placement record per line) + a `<run_id>.summary.json`. This
  is the "persistent individual index for every time it is run" the feature calls for: a
  self-contained, portable, human-readable record of exactly that capture, which can be copied,
  archived or diffed on its own.
- **Master index** — `index/index.sqlite` aggregates every run's records for fast query
  (by hash, by origin path, by origin drive, by destination, by type). The per-run JSONL files
  are the source of truth; the sqlite master is a rebuildable view (`index rebuild` re-reads all
  `runs/*.jsonl`). Losing the DB never loses data.

Location: `~/.local/share/linfilecopy/index/` (XDG data dir), local-only, never leaves the
machine.

### 2.3 Append-only lineage (event model)

The Index is **append-only**. A file that is later re-sorted, moved or relinked by Smart
Organization (§3) does **not** overwrite its old record — a **new placement event** is appended
referencing the same `sha256`. Querying by hash therefore yields the file's **full lineage**:
origin → first destination → every subsequent location, with timestamps. This is what makes
reorganisation **reversible and auditable** (§3), and what lets Smart-Link **re-point stale
links** (§4.4): the Index always knows the current location of a given content identity.

### 2.4 Identity vs provenance

- **Identity = `sha256`.** "The same file" across renames/moves/drives is defined by content
  hash, so a file tracked from Drive A to a sorted tree to a consolidated archive is one lineage
  even though its name and path changed at each step.
- **Provenance = `origin_path` + `origin_drive_uuid`.** Preserved forever, so "restore these as
  they were on the old drive" (§3) is always possible, and so a human can answer "where did this
  come from?" long after the source is gone.

### 2.5 Size, privacy, hygiene

- The Index stores **metadata and hashes only — never file contents**; it is small (hundreds of
  bytes per file) and grows slowly. A 1M-file history is tens-of-MB of sqlite.
- **Local only**, consistent with the build philosophy; no telemetry, no network.
- `index gc` can drop run snapshots older than a chosen horizon *only if* no live link (§4)
  still depends on them; links pin their records so a relink can always resolve.

## 3. Smart File Organization (the feature the Index powers)

With a complete origin⇄destination history, LinFileCopy can reorganise intelligently and
safely. Proposed capabilities (future; this doc defines the substrate, not the final UI):

- **Re-sort without re-copying.** Because the Index knows every file's hash, type and current
  location, a new organisation scheme (by date, by EXIF/taken-time, by source tree, by project,
  by detected kind) can be applied by **moving or linking** existing files, not re-reading
  sources. Each re-sort appends lineage events.
- **Global de-duplication.** The Index exposes every content hash seen across **all runs and all
  drives**, so duplicates that Critical Mass could not see within one run (they were on different
  captures) can be collapsed later — keep one, replace the rest with links (§4).
- **Reconstruct an original view on demand.** "Show/export these files as they were laid out on
  Drive X on <date>" is a pure Index query + a tree of links or a copy — provenance makes the old
  structure recoverable even after flattening.
- **Heuristic suggestions, no external deps.** Grouping is rule/heuristic-based (path-token
  clustering, date bucketing, co-occurrence, extension/MIME), implemented in stdlib — **no ML
  frameworks, no network models**, matching the mandatory build philosophy. Suggestions are
  always previewed and confirmed; the engine never reorganises silently.
- **Reversible.** Every reorganisation is an appended set of events, so an **Undo** re-reads the
  prior placement and moves/links files back. The Index *is* the undo log.

Smart Organization is strictly an **index-driven planner** over the same safe primitives
Critical Mass already uses (plan → preview → confirm → move/link → verify), so it inherits the
verification and resume guarantees.

## 4. Smart-Link — keeping old paths valid after a move

### 4.1 The problem

When a file is captured/sorted/consolidated away from its original path, **other applications
that referenced the old path break**: a photo manager's library, a project file that hard-codes
asset paths, a DAW's sample references, shortcuts, scripts. Moving data should not orphan the
tools that use it. The Index makes the fix possible because it records the exact
original→current mapping for every file — so LinFileCopy can **re-designate the linkage** at the
old location to point at the new object.

### 4.2 Hard-link mode — re-designate internal object linkage (same filesystem)

When the destination is on the **same filesystem** as the source, Critical Mass / Smart
Organization can place the file by **hard link** instead of a byte copy (`os.link`):

- A hard link makes the old path and the new path **two names for the same underlying object
  (inode)** — literally re-designating the internal linkage. Both paths are fully valid; any
  application opening either gets the same bytes.
- **Zero extra space** and **no copy time** — ideal for building a type-sorted view *in place*
  on one drive without duplicating data, or for de-duplication (one inode, many names).
- **No broken references:** the original path keeps working because it still resolves to the
  same inode; deleting one name does not remove the data until the last link is gone (inode link
  count). This is the safest "move" on a single volume — nothing is ever actually detached.
- The Index records `link_kind = hardlink` and both paths, so the relationship is known and the
  file's lineage shows the sorted name and the origin name as links to one identity.

Constraints (enforced via the existing filesystem-capability table): hard links require the
**same filesystem**, apply to **regular files only** (not directories), and are unsupported on
**FAT/exFAT**. Where unavailable, fall back to symlink (§4.3).

### 4.3 Symlink mode — move across drives, leave a pointer

When consolidating **across filesystems/drives** (where a hard link is impossible), the file is
physically copied to the destination and a **symbolic link is left at the original path**
(`os.symlink`) pointing to the new location:

- The old path still resolves (for apps that follow symlinks), while the data now lives on the
  destination drive — so a verified move can **reclaim space on the source** (replace the source
  file with a symlink to the destination) *and* keep the old path working.
- The Index records `link_kind = symlink` and `link_path`, so every such pointer is known.

Caveats (documented and surfaced in the UI): some applications do not follow symlinks; a symlink
on a removable source drive dangles when that drive is detached (the target lives elsewhere);
**FAT/exFAT cannot store symlinks**, and **NTFS symlink** support via `ntfs-3g` is limited. The
UI states, per filesystem, which link modes are available before offering them.

### 4.4 Index-maintained, self-healing links ("smart-link")

Plain symlinks dangle if their target later moves. The **Index makes links self-healing**:
because it always knows the current location for a content identity (§2.3), a **relink** pass
walks the Index and **re-points every recorded link** whenever Smart Organization moves targets
around. Links therefore stay valid across repeated reorganisations — the defining "smart" part.

- `linfilecopy index relink` (and an automatic pass after any reorganisation) verifies each
  recorded `link_path` still points at the live `dest_path`; if the target moved, it rewrites the
  link; if the target is gone, it flags the link rather than silently leaving a dangler.
- A **breadcrumb** option can additionally drop a tiny human-readable `.lfc-moved.txt` /
  `.desktop` pointer at an old location for people browsing the old drive (not just apps).

### 4.5 Interaction with the verified move (Critical Mass §9)

Smart-Link extends Critical Mass's *After verify = Delete* with safer variants:

- **Delete → replace with link.** Instead of unlinking a verified source, replace it with a
  symlink (cross-fs) or convert the placement to a hard link (same-fs) to the confirmed
  destination. Space is reclaimed (cross-fs) or never used (same-fs), and old paths keep working.
- **Same guards apply:** a link is only created after the destination copy is `verified` (§8),
  with the just-before-delete re-check (§9), and nothing is touched while a drive is absent.

### 4.6 Safety and caveats

- **Capability-gated.** Link modes are offered only where the source/destination filesystems
  support them (reuse of the capability table); otherwise the UI explains why and offers a plain
  copy/move.
- **No link loops / no self-links.** The planner refuses a link whose target resolves back onto
  the source path, and realpath-checks to prevent cycles.
- **Backups vs links.** A hard link / same-inode placement is **not a backup** (one copy of the
  data). The UI distinguishes "organise in place (links, no redundancy)" from "copy to another
  drive (redundant)". Consolidation-for-backup always implies a real copy.
- **Removable media.** Links that point onto a removable drive are marked as such; the Index
  knows the target drive UUID, so detaching is detected and the link flagged, not silently
  broken.

## 5. Architecture / where it lives

- `engine/index.py` — the persistent Index: per-run JSONL writers, the sqlite master, append-only
  lineage queries, `rebuild`/`gc`. Pure engine, **no Gtk**; stdlib `sqlite3`, `json`, `hashlib`,
  `os`.
- `engine/smartlink.py` — link planning/creation/relinking via `os.link`/`os.symlink`/`os.readlink`,
  gated by the existing filesystem-capability table. No Gtk.
- `engine/smart_organize.py` — the index-driven reorganisation planner (heuristics, preview,
  undo) reusing Critical Mass's plan→verify→move/link primitives. No Gtk.
- UI (future): an Index/History browser page and a Smart Organize planner page, both reading the
  engine through `GLib.idle_add` like every other page.
- Critical Mass is updated to **write Index records on every run** (its catalog already holds
  everything needed: origin path, hash, dest_path incl. `_copy_NN`, verification) — this is the
  one change needed in the near term; the rest is future work.

## 6. Safety and integrity

- **Index never holds file contents**, only metadata/hashes; local-only; no network.
- **Append-only** — history is never rewritten, so reorganisations are auditable and reversible.
- **Rebuildable** — the sqlite master can be regenerated from the per-run JSONL truth.
- **Links are capability-gated, verified, and self-healing**; a move that would strand a
  reference is blocked or leaves a maintained link, never a silent dangler.
- All destructive or linkage-changing actions are **previewed and confirmed**, consistent with
  the app's safety-first rules.

## 7. Build order

1. **Near-term (ties into Critical Mass):** `engine/index.py` writing the per-run JSONL +
   master sqlite from the Critical Mass catalog on every run. Golden tests for record fidelity
   (origin path, hash, renamed `dest_path`). *This is the part to land alongside Critical Mass.*
2. `index` CLI: `rebuild`, `query` (by hash/origin/dest/type), `gc`.
3. `engine/smartlink.py` + capability gating; hard-link (same-fs) and symlink (cross-fs) placement
   and `relink`; tests on ext4 (full support) with FAT/exFAT/NTFS behaviour mocked.
4. `engine/smart_organize.py`: index-driven re-sort/dedup/reconstruct planner with preview + undo.
5. UI: Index/History browser and Smart Organize planner pages; icons from the local Phosphor set.
6. Docs, changelog, decision record, change manifests; user strings via `_()`.

## 8. Roadmap placement

Tracked in `.claude/memory/pending.md`:
- **Near-term:** Critical Mass writes the persistent per-run Index (origin⇄dest incl. renames).
- **Future (advanced):** Smart File Organization (index-driven re-sort, global dedup, reconstruct,
  undo) and Smart-Link (hard-link/symlink re-designation + self-healing relink).

## 9. Open questions

- **Hash cost at scale.** Hashing every file to key the Index is already done by Critical Mass's
  checksum verification; for *Size*-only runs, is a cheaper identity (size + head/tail sample)
  acceptable, or is full sha256 always required for Index membership?
- **Default link mode.** Same-fs → hard link, cross-fs → symlink is proposed; should "organise in
  place" default to hard links (zero space) or always to a real copy unless explicitly asked?
- **Index scope / retention.** One global Index vs per-destination; how long to keep run
  snapshots; whether `gc` may ever drop lineage that no live link pins.
- **Cross-machine portability.** The per-run JSONL is portable; do we ever want to merge Indexes
  from multiple machines (still local, just imported), and how are drive UUIDs reconciled?
- **Non-following apps.** For applications that ignore symlinks, is a hard-link-only or
  copy-back-on-demand mode needed?
