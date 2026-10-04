# Critical Mass — Technical Concept

> Status: **Proposed (concept)** · Concept version 0.2 · 2026-10-03
> Parent design: [CONCEPT.md](CONCEPT.md) · As-built architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
> Scope: a new LinFileCopy page offering capture strategies, the primary one being an
> aggressive multi-source capture that identifies, catalogs and type-sorts every file into a
> destination — then **verifies every copy, resumes through interruptions, and can delete the
> sources only once 100% confirmed**. Fits the existing constraints: **rsync engine, local
> storage only, no external runtime deps, engine never imports Gtk**.

---

## 1. Summary

**Critical Mass** is a new page (sidebar item, `page_critical_mass.py`) that presents a
**page of options** for bulk-capturing content off one or more storage locations. Its
headline option is **Aggressive Capture**: point it at any list of sources — external drives,
portable drives, mountpoints, folders, or a mix — and it recursively **captures, identifies
and catalogs every file**, then copies each file into a destination **organised by file
type**, one folder per type, with **subtype subfolders** inside each.

It is the "get everything off these drives, make sense of it, and *know it's all safely
there*" tool: recovery / consolidation / migration of messy or failing media. Beyond copying,
Critical Mass:

- **Verifies and confirms** every destination copy — up to a full end-to-end checksum match —
  so the run can assert **100% of source files were copied correctly and organised properly**.
- **Resumes through interruptions** — power loss, USB drop-out, latency, intermittent
  connectivity — picking up exactly where it stopped, never re-copying what is already proven.
- **Optionally deletes the sources** once (and only once) every file is confirmed, turning the
  operation into a **verified move / reclaim**. This is opt-in and hard-guarded.

It never modifies the sources until that final, confirmed delete phase, and every file is
written to a durable **catalog** that is both the audit trail and the resume journal.

```
Destination/
├── files_docs/
│   ├── files_word/      (.doc .docx .odt .rtf)
│   ├── files_text/      (.txt .md)
│   └── files_pdf/       (.pdf)        ← PDF can also be its own top category; see §4
├── files_excel/
│   ├── files_xlsx/      (.xlsx)
│   └── files_csv/       (.csv)
├── files_images/
│   ├── files_jpg/       (.jpg .jpeg)
│   ├── files_png/       (.png)
│   └── files_raw/       (.cr2 .nef .arw .dng)
├── files_video/
│   ├── files_mp4/       (.mp4 .m4v)
│   ├── files_mov/       (.mov)
│   └── files_mkv/       (.mkv)
├── …
├── files_other/         (recognised but uncategorised)
│   └── files_noext/     (no extension / unidentifiable)
└── _catalog/            (manifest + resume journal: what was found, from where, where it
                          went, its hash, and its verification state)
```

## 2. The page of options

The page is a short, legible form (Simple by default, with an Advanced disclosure) built like
the existing Designer. Options:

| Option | What it does | Default |
|---|---|---|
| **Sources** | A **list** the user adds to: drives, mountpoints, folders. Single or many. Each row shows label, free/used, read-only flag. | (empty — user adds) |
| **Destination** | One target directory on a local filesystem (must have room; checked up front). | — |
| **Capture mode** | **Aggressive** (everything) · **By type** (only chosen categories) · **Catalog only** (scan + manifest, copy nothing — a dry run). | Aggressive |
| **Organisation** | **Type → subtype** (`files_video/files_mp4/…`, this doc's default) · **Type only** · **Preserve tree under each type**. | Type → subtype |
| **On duplicate** | **Skip identical** (same hash) · **Keep both** (stamp/suffix) · **Keep newest**. Never silently overwrites. | Skip identical |
| **Identification** | **Extension** (fast) · **Content-verified** (sniff magic bytes / MIME; correct wrong or missing extensions). | Content-verified |
| **Verification** | How strongly to confirm each copy (§7): **Size** · **Checksum** (end-to-end sha256) · **Deep** (checksum + correct taxonomy placement + orphan scan). | Checksum |
| **Resume** | Reuse the catalog of a prior/interrupted run on the same destination: skip already-verified files, finish the rest (§6). | On |
| **After verify** | What to do with the sources once 100% confirmed (§8): **Keep sources** · **Delete sources** (verified move) · **Move sources to trash**. | Keep sources |
| **Delete policy** | Only when deleting: **All-or-nothing** (delete nothing until the whole set is verified) · **Per-file** (delete each source as soon as its own copy is verified). | All-or-nothing |
| **Dedup pass** | Optionally fold byte-identical copies to one (hand off to the LinFileDedup approach). | Off |
| **Safety** | Sources mounted **read-only** for the copy phase; preview summary before start; confirmations for deletes. | On |

The headline/primary flow is **Aggressive + Type → subtype + Content-verified + Checksum
verify + Keep sources**. Switching **After verify** to *Delete sources* upgrades the whole run
to a verified move.

## 3. Pipeline (scan → classify → plan → copy → verify → [reclaim])

Six stages, the engine ones (`engine/critical_mass.py`) with **no Gtk**, reporting progress to
the UI only through `GLib.idle_add` like every other run. Each stage advances a per-file state
in the catalog (§5/§6), written durably so any stage can resume.

1. **Scan** — walk every source recursively (`os.scandir`, with the existing unreadable-path
   tolerance), collecting path, size, mtime. Resilient: an unreadable file or directory is
   logged and skipped, never aborts the capture ("aggressive" = keep going). → state
   `discovered`.
2. **Classify** — map each file to **category → subtype** (§4): by extension, and when
   *Content-verified* is on, confirm/repair via magic-byte / MIME sniffing (stdlib
   `mimetypes` + a small built-in signature table — **no external `python-magic`**). →
   `planned`.
3. **Plan** — compute each destination path `dest/files_<category>/files_<subtype>/<name>`,
   resolve collisions per *On duplicate* (hashing only colliding candidates), and estimate
   totals for the **preview**. Nothing written yet.
4. **Copy** — execute with **rsync** (the only engine) driven by per-bucket `--files-from`
   NUL-separated lists, with resilience flags (§6) so partial transfers survive interruption.
   The existing runner, progress parser, pause/resume and logging all apply. → `copied`.
5. **Verify** — independently confirm each copy to the chosen level (§7); a file is only
   **confirmed** when it passes. → `verified` (or back to `copied`/`error` on mismatch, which
   re-queues it for copy).
6. **Reclaim** *(only if After verify = Delete / Trash)* — once the confirmation gate (§7)
   is satisfied, delete or trash the source files under the §8 guards. → `deleted`.

Because the copy reuses the existing runner, Critical Mass runs appear on the **Active
Transfers** page with the same progress ring and controls as any other job; the page shows an
extra **Verify** and (if enabled) **Reclaim** phase after the copy bar completes.

## 4. Classification taxonomy

A single ordered table maps extensions → `(category, subtype)`. Categories use the user's
`files_<name>` convention; subtypes are `files_<ext-family>`.

| Category folder | Subtype folders (examples) | Matches |
|---|---|---|
| `files_docs` | `files_word`, `files_text`, `files_rtf`, `files_odt` | .doc .docx .txt .md .rtf .odt |
| `files_excel` | `files_xlsx`, `files_xls`, `files_csv`, `files_ods` | .xlsx .xls .csv .ods |
| `files_slides` | `files_pptx`, `files_ppt`, `files_odp` | .pptx .ppt .odp |
| `files_pdf` | `files_pdf` | .pdf |
| `files_images` | `files_jpg`, `files_png`, `files_gif`, `files_heic`, `files_raw`, `files_svg`, `files_tiff` | .jpg .jpeg .png .gif .heic .cr2 .nef .arw .dng .svg .tif .tiff … |
| `files_video` | `files_mp4`, `files_mov`, `files_mkv`, `files_avi`, `files_wmv`, `files_webm` | .mp4 .m4v .mov .mkv .avi .wmv .webm … |
| `files_audio` | `files_mp3`, `files_flac`, `files_wav`, `files_aac`, `files_m4a` | .mp3 .flac .wav .aac .m4a … |
| `files_archives` | `files_zip`, `files_7z`, `files_tar`, `files_rar` | .zip .7z .tar .gz .tgz .rar … |
| `files_code` | `files_py`, `files_js`, `files_web`, `files_shell` | .py .js .ts .html .css .sh … |
| `files_data` | `files_json`, `files_xml`, `files_sql`, `files_db` | .json .xml .yaml .sql .sqlite … |
| `files_other` | `files_noext`, plus `files_<ext>` for recognised-but-uncategorised | anything with a real extension not above |
| `files_other/files_noext` | — | no extension, or sniffing could not identify it |

Rules:
- **Subtype always exists.** Every category folder contains subtype subfolders; a file never
  lands directly in a category folder. Single-member categories (e.g. PDF) still use one
  subtype folder for a uniform tree.
- **Extension families collapse** sensibly: `.jpg`/`.jpeg` → `files_jpg`; `.tif`/`.tiff` →
  `files_tiff`; `.mp4`/`.m4v` → `files_mp4`.
- **Content-verified mode** can move a mislabelled file to the correct subtype (a `.txt` that
  is really a JPEG → `files_images/files_jpg`) and can place extensionless files by signature.
- The table is **data, user-extendable** (a JSON taxonomy under `~/.config/linfilecopy/`), so
  new extensions and custom categories need no code change — mirrors how jobs/templates are
  already stored.

## 5. The catalog (manifest + resume journal)

Every file is recorded in a durable catalog under `dest/_catalog/`. The catalog is the single
source of truth for both the audit trail **and** resume (§6), so it is written transactionally
(sqlite in WAL mode, `synchronous=FULL`) and each state change is committed before the
corresponding filesystem action is considered done.

- `catalog.sqlite` — one row per source file:
  `source_path, source_drive_uuid, source_label, size, mtime, sha256, category, subtype,
  dest_path, state, attempts, verified_at, deleted_at, error`.
- `catalog.csv` — the same, human-readable, openable in a spreadsheet.
- `summary.txt` — totals per category/subtype, bytes moved, duplicates folded, verified count,
  deleted count, errors.

`state` is the file's position in the §6 state machine. Sources are identified by **filesystem
UUID**, not mount path, so a drive that reconnects at a different mountpoint is still matched to
its catalog rows.

## 6. Resumability & interruption tolerance

Critical Mass is designed to **survive power outages, USB/SATA drop-outs, latency and
intermittent connectivity** and continue without re-doing proven work. Two mechanisms:

**(a) A durable per-file state machine in the catalog.** Each file moves strictly forward, and
every transition is committed to sqlite (fsync'd) *before* the filesystem step it authorises:

```
discovered → planned → copying → copied → verified → [delete_pending → deleted]
                 ↘ error (re-queued)            ↘ (mismatch → back to copying)
```

A file is only ever `verified` after an independent check (§7) passes, and only ever `deleted`
after it is `verified` and re-checked at delete time (§8). A crash at any instant leaves the
catalog describing exactly what is proven and what is not.

**(b) Interruption-tolerant copying.** The rsync copy phase uses:
- `--partial --partial-dir=.lfc-partial/` — a half-written file is kept, not discarded, so a
  resumed run continues it instead of restarting (critical for large video files over a flaky
  USB link).
- `--append-verify` — when resuming a partial file, rsync re-checksums the already-transferred
  prefix before appending, so a power-loss-truncated file can never be silently corrupted.
- `--timeout=<n>` — a stalled transfer (hung bridge, drive asleep) aborts the file rather than
  hanging the run; it is re-queued. `orico-keepalive`-style liveliness is out of scope here but
  complementary.
- Retries with backoff (the runner already has this) for transient errors.

**On restart / resume** (the default **Resume = On**), Critical Mass opens the destination's
catalog and:
1. Skips every `verified`/`deleted` file (proven done — zero re-work).
2. Re-verifies `copied`-but-unverified files (a copy finished but the crash happened before the
   verify was recorded).
3. Resumes `copying`/`planned`/`error` files (rsync continues the partial via `--append-verify`).
4. Re-scans sources for anything new since the last scan, adding `discovered` rows.

**Drive disconnect mid-run.** When a source or destination drive vanishes (detected via the
existing `Gio.VolumeMonitor` / mount checks), the run **pauses** and waits for the drive to
reappear **by UUID**, then resumes — rather than failing. Nothing is deleted while any involved
drive is absent.

## 7. Verification & confirmation — what "100%" means

Verification is a **separate stage from copying** and is what lets the run *assert* success. A
file is **confirmed** only when it passes the chosen level:

| Level | Check | Cost | Use |
|---|---|---|---|
| **Size** | Destination exists and byte-size equals the source. | Cheap | Quick sanity; not sufficient to prove integrity. |
| **Checksum** *(default)* | sha256 of the **destination, read back from disk**, equals the sha256 of the source. End-to-end: proves the bytes on the destination media are correct, not just that rsync reported success. | One full read of each side | The default, and **mandatory** whenever *After verify = Delete*. |
| **Deep** | Checksum **plus**: the destination file is at its **planned taxonomy path** ("organised properly"), and a reverse scan finds **no orphan/extra** files the catalog does not explain. | + a destination tree scan | Migration / before deleting sources. |

**The confirmation gate.** A run reports **complete** only when, for every non-error source
file, `state = verified` and the counts reconcile: *source files found == destination files
confirmed*, with bytes and per-category totals matching the plan. Any shortfall (missing file,
hash mismatch, orphan under Deep) is surfaced as a blocking result with the exact list, and the
run is **not** marked successful. Hashes are computed once and cached in the catalog (used for
dedup/collision too), so verification does not re-hash needlessly.

This gate is the precondition for any source deletion (§8): **no confirmation, no delete.**

## 8. Deleting sources safely (verified move)

*After verify = Delete* makes Critical Mass a **verified move**: sources are removed only after
their copies are proven. This is the one destructive capability, and it is guarded accordingly.

- **Opt-in and off by default.** The default is *Keep sources*. Enabling *Delete sources*
  requires an explicit confirmation dialog stating the file count and total bytes to be deleted,
  consistent with LinFileCopy's "confirm deletes with the number of files" rule.
- **Verification is forced to Checksum (or Deep).** Deletion cannot run on *Size*-only
  verification — integrity must be proven end-to-end first.
- **Delete policy:**
  - **All-or-nothing** (default): delete **nothing** until the entire set passes the §7
    confirmation gate; then delete. Safest — a failure anywhere leaves all sources intact.
  - **Per-file**: delete each source the moment its own copy is `verified`. Frees space as it
    goes (useful when the destination is tight or sources are nearly full), at the cost of
    deleting before the whole set is proven.
- **Just-before-delete re-check (TOCTOU guard).** Immediately before unlinking each source,
  Critical Mass re-confirms: the destination file still exists and still matches its recorded
  hash/size, and the destination drive is still mounted. If anything is off, that file (and,
  under All-or-nothing, the whole delete phase) is aborted and kept.
- **Never deletes:** anything not `verified`; anything whose destination drive is not currently
  mounted; or when any file in the set errored (All-or-nothing). It deletes what it safely can,
  keeps the rest, and reports precisely which and why.
- **Trash option.** *Move sources to trash* relocates sources to a `.lfc-trash/`-style area
  instead of unlinking (reusing the two-way-sync trash + `free_name` machinery) for users who
  want a recoverable step. Note: trash on the *same* source drive does not reclaim space; the
  UI says so.
- **The catalog is the receipt.** Every deletion records `deleted_at`; `summary.txt` reports
  how many sources were deleted vs kept, so the operation is fully auditable after the fact.

## 9. Safety (overall)

Consistent with LinFileCopy's safety-first rules:

- **Copy-only until confirmed.** Sources are untouched through scan/copy/verify; the only write
  to a source is the §8 delete, which happens only after §7 confirmation.
- **Read-only sources during copy.** Where the OS allows, sources are (re)mounted read-only for
  the copy phase.
- **Never overwrite** on the destination. Collisions follow *On duplicate*; *Keep both* uses a
  unique suffix (as two-way sync's trash already does via `free_name`).
- **Destination guarded.** Cannot be `/`, a system directory, or inside any source
  (realpath-checked, reusing the source-inside-destination guard).
- **Preview first.** The plan's totals and a sample of the resulting tree are shown and must be
  confirmed before any copy; deletion has its own second confirmation.
- **Space checked up front**, per filesystem, before starting.
- **Resilient, not reckless.** Unreadable files are logged and skipped; the run continues and
  the catalog marks them `error`, and the confirmation gate (§7) refuses to call such a run
  100% — so an error can never be mistaken for success, and can never authorise a delete.

## 10. Build order

1. `engine/taxonomy.py` — the extension/MIME → (category, subtype) table + user-JSON override;
   stdlib signature sniffer. Golden tests.
2. `engine/catalog.py` — the durable sqlite catalog + state machine (WAL, transactional
   transitions), resume logic, CSV/summary export. Tested with simulated crashes (kill between
   transition and filesystem step; assert resume correctness).
3. `engine/critical_mass.py` — scan, classify, plan, collision resolution, driving copy →
   verify → reclaim over the catalog. Pure engine, no Gtk; tested without a display against a
   fixture tree, including induced mismatches and interrupted/resumed runs.
4. Copy wired to the existing rsync runner via per-bucket `--files-from` + `--partial`/
   `--append-verify`/`--timeout`; reuses `RunManager`, progress parsing, pause/resume, history,
   and drive-disconnect pause/resume.
5. Verify stage: streamed sha256 of both sides (cached), size/placement/orphan checks per level.
6. `ui/pages/page_critical_mass.py` — the options form (Simple/Advanced), source-list widget,
   preview panel, Verify/Reclaim phase display, start → Active Transfers; delete confirmations.
7. Catalog viewer (later): a results view reading `catalog.sqlite` (what went where, verified,
   deleted).
8. Docs, changelog, decision record, change manifest; new user strings via `_()`; any new icons
   added to `tools/icons.manifest` (local Phosphor only).

## 11. Open questions

- **PDF placement** — its own top category `files_pdf`, or a subtype under `files_docs`?
- **Archives** — copy as-is (default), or optionally expand and classify contents?
- **Subtype granularity** — how fine? (e.g. RAW split per-vendor, or one `files_raw`.)
- **Case-insensitive / FAT/exFAT destinations** — folder-name case and the 4 GiB file limit
  need the per-filesystem handling the planner already does.
- **Dedup scope** — within this capture only, or against what the destination already holds?
- **Verify-on-resume cost** — re-verify `copied`-but-unverified files by full checksum (safe,
  slower) or trust size when the catalog shows a clean rsync exit (faster)? Proposed: full
  checksum whenever *After verify = Delete*, size otherwise.
- **Per-file delete vs all-or-nothing default** — all-or-nothing is proposed as the default for
  safety; confirm that matches the expected "reclaim space as you go" use case.
