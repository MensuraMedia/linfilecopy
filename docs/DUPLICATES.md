# Duplicates — Advanced Technical Concept

> Status: **Proposed (advanced / future)** · Concept version 0.1 · 2026-10-03
> Builds on: [CRITICAL_MASS.md](CRITICAL_MASS.md) (name-collision `_copy_NN` scheme),
> [INDEX_AND_SMART_ORGANIZATION.md](INDEX_AND_SMART_ORGANIZATION.md) (persistent hash index).
> Reference implementation studied: **LinFileDedup** at `/home/user/projects/linfilededuplication`
> (GTK4/libadwaita; its exact-duplicate engine, hash cache, progress rings and worker/queue
> architecture). Where that app lacks a behaviour this feature needs, it is called out as
> **net-new** below.
> Constraints unchanged for LinFileCopy: **local storage only, no external runtime deps**
> (stdlib `hashlib` only — no `xxhash`/`Pillow`), **GTK 3**, **engine never imports Gtk**, UI
> updated only via `GLib.idle_add`.

---

## 1. Summary

**Duplicates** is a new LinFileCopy page (`page_duplicates.py`). Point it at a folder and it
**hashes every file**, **indexes the work, the hash and the result per file**, and reports two
distinct findings:

1. **Exact 1-to-1 duplicates** — files whose *contents* are byte-identical (same SHA-256,
   optionally byte-verified), regardless of name or location.
2. **Name conflicts** — files that **share the same name but are in fact different files**
   (same basename, different content). These are **not** duplicates; they would collide if ever
   merged into one folder, so Duplicates flags them and **recommends a rename** (reusing Critical
   Mass's `MyFile_copy_01.ext` scheme, §3.2 / CRITICAL_MASS §5).

It works for **all file types by default**, with options to **ignore/avoid specific types**
(e.g. disk images). Because hashing large files takes real time, when it encounters
**substantial files** it shows a **time-table of expected durations** — per large file and in
total — and lets the user proceed, skip individual files, or skip all large files, **before** the
long work begins (§7, net-new vs LinFileDedup).

Every per-file hash it computes is written to a **persistent hash index** (§5) so re-runs skip
unchanged files, and so the results feed the cross-run Index and Smart Organization
(INDEX_AND_SMART_ORGANIZATION.md).

## 2. Relationship to LinFileDedup and to the other LinFileCopy features

**Borrowed from LinFileDedup** (`src/linfilededuplication/`), adapted to LinFileCopy's rules:

| LinFileDedup (reference) | Adapted here |
|---|---|
| Tiered exact-dup engine: size bucket → 64 KiB prefix hash → full SHA-256 (1 MiB chunks) → optional byte-verify → hard-link collapse (`core/scanner.py:find_exact_groups`, `core/hashers.py`) | Same pipeline, §4 — the proven, near-optimal way to find exact dups without hashing everything. |
| Prefix hash uses xxHash64 if available else BLAKE2b; full hash SHA-256 (`core/hashers.py`) | **Stdlib only:** prefix = BLAKE2b (`hashlib.blake2b`, 64 KiB, 16-byte digest); full = SHA-256. No `xxhash` dependency. |
| Persistent `HashCache` JSON keyed by `(dev, ino, size, mtime)`, cap 300k (`core/hashcache.py`) | Same idea, §5, and it doubles as input to the persistent Index. |
| Worker `ScanThread` → `queue.SimpleQueue` → `ScanController` drains with `GLib.timeout_add` (16 ms tick, 8 ms budget, yield every 64 events) → GObject signals (`services/scan_controller.py`) | Worker thread + drained queue, §9, but following LinFileCopy's existing `GLib.idle_add` event convention / run-card wiring. |
| `RingLoader` donut % ring, per-source rings + current-file labels + pulsing bars (`ui/widgets/ring_loader.py`, `ui/pages/scan.py`) | Reuse LinFileCopy's existing **`ProgressRing`** (already added to the run cards) + progress bars, §8. |
| Type include/exclude, categories, `LARGE_TYPES`, `min_size` (`core/options.py`, `core/filetypes.py`); include-all when empty | Same model, §6. |
| Cooperative cancel via `threading.Event`, checked between files and every 1 MiB chunk (`core/hashers.py`) | Same, §9. |

**Net-new (LinFileDedup does not do these):**
- **Same-name / different-content detection** — LinFileDedup groups *only* by content; filenames
  are cosmetic there. §3.2 adds name-conflict detection.
- **Duration / ETA time-table** — LinFileDedup shows only a done/total **count** fraction and a
  static "large files may take several minutes" note; it measures no throughput and projects no
  time. §7 adds a bytes-weighted ETA and a pre-hash time-table for large files.

**Ties to LinFileCopy features:** Duplicates is the detection engine behind Critical Mass's
*Dedup pass* option; its rename recommendations use the Critical Mass `_copy_NN` scheme; and its
per-file hashes populate the persistent Index, so a file hashed here need not be re-hashed by a
later capture or verification.

## 3. What it detects

### 3.1 Exact 1-to-1 duplicates (content identity)

Files are duplicates when their **contents** match — same SHA-256, and (optionally) a final
byte-for-byte compare. Name and path are irrelevant: `IMG_1001.jpg` and `holiday/photo.jpg`
with identical bytes are one group. Hard-linked files that already share an inode are collapsed
to one (they are already a single physical file — nothing to reclaim), exactly as LinFileDedup
does (`scanner.py` inode collapse). Output: **duplicate groups**, each with a suggested keeper and
the reclaimable byte total.

### 3.2 Name conflicts (same name, different content) — net-new

Independently of content grouping, Duplicates buckets files by **basename** (case-folded on
case-insensitive filesystems). A basename owned by **two or more distinct content hashes** is a
**name conflict**: the files are *not* duplicates, but they share a name and would overwrite each
other if merged. For each conflict Duplicates reports the clashing files and a **recommended
rename** following Critical Mass §5 — the first keeps the name, the rest become
`MyFile_copy_01.ext`, `MyFile_copy_02.ext`, … This is precisely the "same name but in fact a
different file → warrants a name change" case.

The two findings compose cleanly from one pass over the index:
- group by `sha256` → **duplicates** (§3.1);
- group by `basename` → buckets; a bucket spanning >1 `sha256` → **name conflict** (§3.2);
- a bucket with one `sha256` but many names → just duplicates with different names (§3.1).

## 4. The hashing pipeline (stdlib, tiered)

Mirrors LinFileDedup's `find_exact_groups`, implemented with `hashlib` only. Each tier exists so
that the expensive full read is done for as few files as possible.

1. **Enumerate + size-bucket.** Walk the folder with `os.scandir` (honouring §6 filters),
   recording `path, size, mtime, dev, ino`. Bucket by exact byte **size**; any file with a unique
   size **cannot** have an exact duplicate and is never hashed. (This is also why the work is
   *not* O(n²): a file is only ever compared within its own size/prefix bucket.)
2. **Prefix hash** (`hashlib.blake2b`, first **64 KiB**, 16-byte digest) for every file in a
   size-collision bucket; sub-bucket by prefix. Prefix-unique files drop out. Cheap: one small
   read each.
3. **Full SHA-256** (streamed in **1 MiB** chunks) for files surviving the prefix stage, reusing
   a cached digest when the index (§5) shows the file unchanged. Sub-bucket by full digest.
4. **Byte-verify (optional, default on for destructive actions).** Lock-step byte compare of a
   digest group's members, stopping at first difference — rules out the astronomically rare
   SHA-256 collision before any file is trusted as a duplicate.
5. **Hard-link collapse.** Members already sharing `(dev, ino)` fold to one.
6. **Emit groups.** A surviving group of ≥2 distinct files becomes a duplicate group; name-conflict
   buckets (§3.2) are emitted alongside.

Cancellation is checked between files and on **every 1 MiB chunk**, so a Stop aborts promptly even
mid-read of a multi-GB file (as in LinFileDedup `hashers.py`).

## 5. Per-file hash index (indexing the work)

Every hash computed is recorded, so work is never repeated and results are inspectable — the
"index the work, hash and result per file" requirement.

- **Schema** (per file): `path, dev, ino, size, mtime, prefix_hash, sha256, is_hardlink,
  group_id, name_conflict_id, scanned_at`.
- **Cache semantics** (from LinFileDedup `HashCache`): a lookup is a **hit** only when
  `(dev, ino, size, mtime)` all match the stored row; any change is a miss → re-hash. So a
  re-scan of a mostly-unchanged folder is nearly instant.
- **Storage:** `~/.local/share/linfilecopy/duplicates/hashindex.sqlite` (sqlite, parameterised),
  capped/vacuumed like LinFileDedup's 300k-entry cap. A per-run report (groups, conflicts,
  reclaimable bytes, durations) is also written for the UI and export.
- **Feeds the global Index.** These `(path, size, mtime, sha256)` rows are exactly what
  INDEX_AND_SMART_ORGANIZATION.md §2 needs; Duplicates contributes them so a file hashed here is
  already known to Critical Mass verification and Smart Organization. The hash is computed once
  and reused everywhere.

## 6. File-type and size filtering (all types by default)

Modelled on LinFileDedup `core/options.py` + `core/filetypes.py`:

- **Include all types by default.** An empty include-list means "every type" (LinFileDedup's rule).
- **Ignore / avoid types.** An **exclude list** of extensions (e.g. `.iso`, `.vdi`, `.vmdk`,
  `.img`) removes them from the scan — offered as one-tap toggles for a built-in **`LARGE_TYPES`**
  catalogue (disk images, VM images) plus a free-form list, so the user can skip exactly the
  heavy types they don't want hashed.
- **Category toggles.** The same Images / Video / Music / Documents groupings LinFileDedup shows,
  for quick include/exclude.
- **Other filters:** `min_size` (default 1 byte — skip empties), hidden-file inclusion
  (default off), symlink following (default off), glob/path exclusions and per-subtree ignore.
- **No hard max-size filter**; instead, large *types* are excluded by extension, and large
  *files* are governed by the time-table (§7) rather than silently skipped.

## 7. Duration and the large-file time-table (net-new)

LinFileDedup projects no time. Duplicates adds an **honest ETA** and, for substantial files, a
**pre-hash time-table**, because hashing reads bytes and bytes take time.

### 7.1 Throughput measurement

- Work is weighted by **bytes**, not file count (LinFileDedup weights by count, so a 10 GB file
  and a 1 KB file advance its bar equally — this fixes that). After the size+prefix stages the
  engine knows **exactly how many bytes must be fully hashed** (`bytes_to_full`).
- **Throughput** (MiB/s) is measured live as `hashed_bytes / elapsed`, smoothed with an EWMA, and
  seeded by a short **calibration** (hash the first ~256 MiB of candidate data and time it, or use
  the last run's measured rate from the index). Disk read speed dominates and is fairly stable per
  device, so the estimate converges quickly.
- **Overall ETA** = `(bytes_to_full − hashed_bytes) / throughput`, displayed and updated live
  (§8). Separate, cheaper estimates cover the prefix stage.

### 7.2 The large-file prompt

- A file is **substantial** when its size ≥ a threshold (default **512 MiB**, LinFileDedup's
  `_LARGE_FILE`; user-configurable). 
- Before the full-hash stage, if the candidate set contains substantial files, Duplicates shows a
  **time-table dialog** listing each large file with its **estimated hash duration**
  (`size / throughput`, specified as e.g. `18.2 GiB — ~3 min 20 s`), a **total estimated
  duration** for the run, and the throughput assumption. The user can:
  - **Proceed** (hash everything),
  - **Skip selected** large files (they are reported as "not checked" rather than silently
    ignored), or
  - **Skip all large files** (fast pass over everything else).
- "Check the file against all other files" is reassuringly cheap in practice: a large file is only
  **fully hashed if it first collides on size *and* 64 KiB prefix** with another file. If its size
  or prefix is unique, it is *never* fully read, and the time-table says so (shown as "prefilter:
  unique size/prefix — skipped"). So the quoted durations reflect the **actual** bucketed work,
  far less than a naive all-pairs comparison.

## 8. Progress UI

Reusing LinFileCopy's existing Cairo **`ProgressRing`** (the donut added to the run cards) and
progress bars, informed by LinFileDedup's Scan/Results pages:

- A **per-folder/per-source ring** and an **overall ring** with the centred percentage.
- Live **information** (richer than LinFileDedup, which shows no numbers live): current file name
  (extension highlighted), **files done/total**, **bytes done/total**, **elapsed**, and — the
  net-new part — **estimated remaining (ETA)** and **current throughput (MiB/s)**.
- Phase caption: `enumerating → prefiltering (size) → prefix hashing → full hashing → verifying`.
- An indeterminate ring during enumeration (no known total yet), matching how `ProgressRing`
  already animates when a run has no percentage.
- Results view: duplicate groups (keeper first, reclaimable bytes) and a separate **Name
  conflicts** list with the recommended `_copy_NN` renames; a before/after space summary like
  LinFileDedup's `SpaceChart` if dup removal is offered.

## 9. Architecture

- `engine/duplicates.py` — enumerate, size/prefix/full pipeline (§4), name-conflict detection
  (§3.2), ETA/throughput (§7). **Pure engine, no Gtk**; stdlib `hashlib`, `os`, `sqlite3`.
- `engine/hashindex.py` — the persistent per-file index/cache (§5), shared with the global Index.
- Runs on a **worker thread** (like LinFileDedup's `ScanThread`); progress and group events reach
  the UI through LinFileCopy's established **`GLib.idle_add`** path (LinFileDedup instead drains a
  `SimpleQueue` via `GLib.timeout_add` with an 8 ms budget — an option if event volume is high, but
  the house convention here is `idle_add`).
- **Cancellation:** cooperative `threading.Event`, checked between files and every 1 MiB chunk. No
  pause/resume in v1 (as LinFileDedup).
- `ui/pages/page_duplicates.py` — folder/source picker, type/size options, the time-table dialog,
  live rings/labels, results with dup groups + name conflicts. Icons from the local Phosphor set.

## 10. Outputs, actions and safety

Duplicates is primarily a **detector/advisor**; LinFileCopy's safety-first rules govern any action.

- **Report (always).** Duplicate groups, name conflicts with recommended renames, reclaimable
  bytes, durations, and the list of anything "not checked" (skipped large files, unreadable files).
  Exportable (CSV/JSON) from the per-run report.
- **Rename name-conflicts (opt-in).** Apply the recommended `_copy_NN` renames; previewed and
  confirmed; never overwrites (reuses `free_name`).
- **Resolve exact duplicates (opt-in).** Hand a group to an action: **Trash** non-keepers
  (recoverable, default) or **replace with a hard link / symlink** to the keeper (Smart-Link,
  INDEX §4) to reclaim space while keeping every path valid. Deletions require explicit
  confirmation with counts (app rule), go to Trash by default (as LinFileDedup does), and the index
  is invalidated for changed paths afterwards.
- **Read-only during detection.** Scanning never modifies files; byte-verify is on before any
  destructive resolution so a hash collision can never cause a wrong delete (LinFileDedup's safety
  net).
- **Resilient.** Unreadable files are logged and reported, never abort the scan.

## 11. Build order

1. `engine/hashindex.py` — persistent `(dev,ino,size,mtime)->(prefix,sha256)` cache (sqlite),
   shared with the global Index. Golden tests incl. hit/miss on mtime/size change.
2. `engine/duplicates.py` — tiered pipeline (size→prefix→sha256→verify→inode-collapse) and
   name-conflict grouping; pure engine, no Gtk; tests with fixtures (same-content/different-name,
   same-name/different-content, hard-linked, unique-size fast path).
3. Throughput/ETA + large-file time-table (§7); tests assert bytes-weighted progress and that
   unique size/prefix files are never fully hashed.
4. Worker thread + `GLib.idle_add` event plumbing; cooperative cancel.
5. `ui/pages/page_duplicates.py` — options, time-table dialog, live rings (reuse `ProgressRing`),
   results (dup groups + name conflicts), export.
6. Optional actions: rename conflicts (`_copy_NN`), trash/hard-link resolve (confirm + Trash).
7. Docs, changelog, decision record, change manifest; user strings via `_()`; icons in the manifest.

## 12. Roadmap placement

Tracked in `.claude/memory/pending.md`:
- **Duplicates** page — tiered stdlib hashing, per-file hash index, exact-duplicate groups **and**
  net-new same-name/different-content detection with `_copy_NN` rename recommendations; all types
  by default with ignore-type options; net-new large-file **time-table/ETA**; reuses `ProgressRing`;
  feeds the global Index and backs Critical Mass's dedup pass.

## 13. Open questions

- **Prefix size / algorithm.** 64 KiB BLAKE2b prefix (LinFileDedup's size, stdlib algo) — keep, or
  add head+tail sampling for very large files to cut prefix-collision false positives?
- **Name-conflict scope.** Within the scanned folder only, or across the whole global Index (flag a
  new file that name-clashes with something captured on another drive earlier)?
- **Calibration vs cold ETA.** Seed throughput from the last run's measured rate (per device, stored
  in the index) vs a fresh 256 MiB calibration each run?
- **Multi-threaded hashing.** LinFileDedup hashes sequentially in one worker; on fast NVMe a small
  read pool could help, but risks thrashing spinning/USB drives. Default sequential; pool as an
  opt-in?
- **Action surface.** How much dup *removal* belongs in a copy app vs deferring removal to
  LinFileDedup and keeping Duplicates advisory + rename-only here?
