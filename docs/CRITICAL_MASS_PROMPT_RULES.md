# Critical Mass — Prompt Rules

> Status: **Proposed (concept)** · Concept version 0.1 · 2026-10-04
> Part of: [CRITICAL_MASS.md](CRITICAL_MASS.md) · related:
> [DUPLICATES.md](DUPLICATES.md), [INDEX_AND_SMART_ORGANIZATION.md](INDEX_AND_SMART_ORGANIZATION.md)
> Scope: a **data-driven rule set** that, during a Critical Mass run, detects conditions worth the
> user's attention — a **large file**, a **huge folder**, a **complex/regenerable folder such as a
> `venv`** — and **prompts the user to take a predesignated action** (skip, bundle, preserve-tree,
> quarantine, include, …) **before** any copy happens. Rules are evaluated at Plan time, coalesced
> so the user is never spammed per-file, and every decision is recorded in the catalog.
> Constraints unchanged: local only, no external runtime deps (stdlib `tarfile`/`zipfile`/`os`),
> engine never imports Gtk, UI via `GLib.idle_add`.

---

## 1. Summary

Aggressive capture flattens everything into type/subtype folders (CRITICAL_MASS §4). That is
exactly wrong for some inputs: a Python **`venv`** or a **`node_modules`** is tens of thousands of
tiny, regenerable files that would pollute the type folders and the catalog; a **40 GB video** is
worth a time estimate and a yes/no before it is hashed and copied; a **huge folder** might be
better captured as one archive than exploded file-by-file.

**Prompt Rules** are the mechanism that catches these. Each rule has a **trigger** (a condition on
file/folder metrics or a folder **signature**), a **predesignated default action**, and a flag for
whether to **prompt** or apply silently. During Plan, Critical Mass evaluates every file and folder
against the active rules, **coalesces** the hits (one prompt per rule, with counts and totals — not
one per file), and shows them in the preview for the user to confirm, override, or "remember".
Nothing is copied, skipped, bundled or deleted until the user resolves the prompts.

## 2. Where this fits in the Critical Mass pipeline

A rule-evaluation step sits inside **Plan** (CRITICAL_MASS §3, stage 3), before any copy:

```
scan → classify → [ RULE EVALUATION → coalesced prompts → user resolves ] → plan → copy → verify → [reclaim]
```

- **Scan** produces the file/folder tree with sizes, counts, depths, names.
- **Rule evaluation** runs every rule against each file and each folder, producing **hits**.
- Hits are **coalesced by rule** and surfaced in the preview's **"Review" panel**; `block`-level
  hits must be resolved before the run can start, `warn`-level default to their predesignated
  action but can be changed, `info`-level apply silently and are just listed.
- The resolved decisions rewrite the plan (some subtrees skipped, some bundled, some preserved) and
  are written to the catalog, so a resumed run (CRITICAL_MASS §7) does not re-prompt.

The same rule engine is reusable by the **Duplicates** scan (DUPLICATES.md) and any future
scan-based feature.

## 3. The rule model

Rules are **data, not code** — a JSON file (`~/.config/linfilecopy/prompt_rules.json`, with a
shipped default set), editable by the user and extendable without a release, mirroring how the
taxonomy and job templates are already stored.

```jsonc
{
  "id": "python-venv",
  "label": "Python virtual environment",
  "scope": "folder",                 // "file" | "folder"
  "when": {                           // all present conditions must match (AND)
    "signature": ["pyvenv.cfg", "bin/activate"],   // marker files/dirs (any)
    "name_glob": ["venv", ".venv", "env"],         // optional name match
    "min_size": null, "min_files": null, "min_depth": null
  },
  "severity": "warn",                 // "info" | "warn" | "block"
  "default_action": "skip",           // see §5
  "prompt": true,                     // prompt, or apply default silently
  "remember": true,                   // offer "apply to all like this / always"
  "priority": 50                      // higher wins when several rules match one target
}
```

- **Matching:** a target (file or folder) is tested against every rule of its scope. Conditions in
  `when` are ANDed; a rule with several `signature`/`name_glob` entries matches if **any** of them
  hit. When multiple rules match one target, the **highest `priority`** decides the action (ties →
  most specific / most conservative).
- **Severity:** `block` (must resolve), `warn` (prompt, pre-selected default), `info` (auto-apply,
  listed only).
- **Remember:** when `remember` is true, resolving a prompt can write a lightweight **remembered
  decision** (e.g. "always skip `node_modules`") back to the rules file as an auto-apply, so future
  runs stop asking.

## 4. Triggers / metrics

Rules can condition on any of these, computed during Scan:

**File-scope**
- `min_size` / `max_size` — e.g. ≥ 512 MiB "large", ≥ 4 GiB "very large" (and the FAT/exFAT **4 GiB
  limit** on the *destination* as a hard `block`).
- `ext` / `ext_not` — extension include/exclude (complements CRITICAL_MASS §6 type filters).
- `age` — mtime older/newer than N days.
- `is_symlink`, `is_hardlink` (link-count > 1).
- `name_glob` — e.g. `*.part`, `*.tmp`, `~$*`, `.DS_Store`, `Thumbs.db`.

**Folder-scope**
- `min_size` — total bytes of the subtree (e.g. ≥ 5 GiB "huge folder").
- `min_files` — file count in the subtree (e.g. ≥ 50 000 "very complex").
- `min_depth` — nesting depth (e.g. ≥ 12, or paths that would exceed the destination's path-length
  limit → `block` with an auto-shorten/preserve option).
- `tiny_ratio` — fraction of files under, say, 4 KiB (a signal of a package/cache tree).
- `symlink_ratio` — fraction of entries that are symlinks (a link farm).
- `signature` — **marker files/dirs** that identify a known folder kind (§7).

These feed a per-folder **complexity score** (§7) so even unrecognised-but-pathological folders
(huge count + high tiny-ratio) can trip a generic "complex folder" rule.

## 5. Predesignated actions

The action a rule applies (or offers):

| Action | Effect |
|---|---|
| **include** | Capture normally — flatten into type/subtype folders (the default behaviour). |
| **preserve-tree** | Copy the folder but keep its internal structure under a dedicated `preserved/<name>/…` area instead of flattening (for folders whose layout matters — a project, an app bundle). |
| **bundle** | Pack the whole folder into **one** archive (stdlib `tarfile`/`zipfile`) placed in `files_archives/files_tar/` (or a `files_bundles/`), capturing it as a single unit without exploding it across type folders. Optionally keep a sidecar listing of contents. |
| **quarantine** | Copy into a separate `_review/<rule>/…` area for the user to decide later — captured, but out of the main sorted tree. |
| **skip** | Do not capture; record as `skipped-by-rule` in the catalog (a skip is **not** a delete — sources are untouched). |
| **exclude-permanent** | Skip **and** write a remembered exclusion so future runs never scan it. |
| **confirm** | Capture, but only after an explicit confirm (used for `block` conditions like the 4 GiB limit). |
| **defer** | Leave the prompt unresolved; the run will not start until it is resolved (a parked `block`). |

Large-file rules additionally pull in the **time-table** (CRITICAL_MASS §7 / DUPLICATES §7): the
prompt shows the file's estimated hash/copy duration (e.g. `18.2 GiB — ~3 min 20 s`) so
"include vs skip vs quarantine" is an informed choice.

## 6. The default (shipped) rule set

Sensible predesignated defaults, all user-overridable:

| id | Matches | Severity | Default action | Prompt? |
|---|---|---|---|---|
| `python-venv` | `pyvenv.cfg` / `bin/activate` (names `venv`,`.venv`,`env`) | warn | **skip** | yes (remember) |
| `node-modules` | dir name `node_modules` | warn | **skip** | yes (remember) |
| `pycache` | dir `__pycache__`, `*.pyc` | info | **skip** | no |
| `git-internals` | dir `.git/` | warn | **skip `.git/`, keep working tree** (or bundle to keep history) | yes |
| `build-output` | `build/`,`dist/`,`target/`,`out/`,`.next/`,`bin/`+`obj/` | warn | **skip** | yes (remember) |
| `pkg-caches` | `.cache/`,`.gradle/`,`.m2/`,`vendor/`,`.cargo/`,`.npm/` | warn | **skip** | yes (remember) |
| `ide-config` | `.idea/`,`.vscode/` | info | **skip** | no |
| `os-cruft` | `System Volume Information`,`$RECYCLE.BIN`,`.Trash*`,`lost+found`,`.Spotlight-V100`,`.fseventsd` | info | **skip** | no |
| `app-bundle` | `*.app`,`*.photoslibrary`,`*.sparsebundle` | warn | **bundle** | yes |
| `large-file` | file ≥ 512 MiB | warn | **include** (+ time estimate) | yes |
| `very-large-file` | file ≥ 4 GiB | warn | **confirm** (+ time estimate) | yes |
| `fat-4gib-limit` | file ≥ 4 GiB **and** destination is FAT/exFAT | block | **confirm** (cannot store; skip or pick another dest) | yes |
| `huge-folder` | subtree ≥ 5 GiB | warn | **prompt: bundle / preserve-tree / skip** | yes |
| `very-complex-folder` | subtree ≥ 50 000 files, or high `tiny_ratio` | warn | **prompt: bundle / preserve-tree / skip** | yes |
| `deep-or-long-path` | depth ≥ 12, or path exceeds destination limit | block | **preserve-tree / auto-shorten / skip** | yes |
| `symlink-farm` | `symlink_ratio` high | warn | **skip links (record targets)** | yes |
| `temp-junk` | `*.tmp`,`*.part`,`~$*`,`.DS_Store`,`Thumbs.db` | info | **skip** | no |

Rationale: regenerable toolchain/cache folders default to **skip** (flattening them is noise and they
rebuild from source), app/data bundles default to **bundle** (keep them whole), and size/complexity
conditions **prompt** so the user stays in control of time and layout. All of this is a default a user
can retune or disable.

## 7. Folder complexity & signature detection

- **Signature detection** is the reliable path: a folder is classified by the presence of **marker
  files/dirs** (`pyvenv.cfg` → venv, `package.json`+`node_modules` → JS project, `.git/` → repo),
  checked cheaply during the scan without descending the whole subtree first.
- **Complexity score** (for folders that match no signature) combines `file_count`, `total_size`,
  `depth`, and `tiny_ratio` into a single score; crossing a threshold trips the generic
  `very-complex-folder` rule. This catches pathological-but-unknown trees (e.g. a bespoke cache).
- **Regenerability** is a property the default rules encode: toolchain/build/cache folders are
  marked regenerable (safe to skip — they come back from source), whereas data/app bundles are not
  (so they default to bundle/preserve, never silent skip).
- Detection short-circuits descent: once a folder is classified `skip`/`bundle`, Critical Mass does
  **not** walk its thousands of children for per-file rules — the folder is handled as a unit, which
  also keeps the scan fast.

## 8. Prompt UX and coalescing

The cardinal rule: **never death-by-dialog.** Prompts are aggregated, not per-file.

- **One prompt per rule**, summarising the hits: *"3 Python virtual environments — 420 MB, 52,104
  files total — [Skip all] [Bundle each] [Include] · ☐ remember for future runs"*. Expandable to the
  list of paths.
- **Review panel in the preview.** All `warn`/`block` hits appear as a resolvable list in the Plan
  preview (CRITICAL_MASS §3) with their pre-selected default action; the user adjusts any, then
  confirms once. `info` hits are shown in a collapsed "applied automatically" summary.
- **Remember / apply-to-all.** Resolving with "remember" writes an auto-apply decision back to the
  rules file (§3), so the next capture of the same kind does not ask.
- **Blocking vs non-blocking.** `block` hits (4 GiB-on-FAT, over-long paths) must be resolved before
  Start enables; `warn` hits have a safe default so a user can just click Start.
- **Time-aware.** Large-file and huge-folder prompts carry the estimated duration (§5), so the user
  trades time against completeness knowingly.

## 9. Interaction with the rest of Critical Mass

- **Catalog.** Every rule decision is recorded per target (`rule_id`, `action`, `remembered`), so the
  run is auditable and a **resume never re-prompts** (CRITICAL_MASS §7 reads the recorded decisions).
- **Verification.** Bundled/preserved outputs are verified like any copy (CRITICAL_MASS §8): a bundle
  is verified by its own checksum and a content listing; a skipped source is recorded as
  `skipped-by-rule`, never counted as copied, so the 100% confirmation gate stays honest.
- **Verified move / delete.** A `skip` is **not** a delete — skipped sources are left intact. Only
  files that were captured **and** confirmed are ever eligible for the opt-in source deletion
  (CRITICAL_MASS §9); skipped/quarantined files are always kept.
- **Index.** Bundles and preserved trees still get Index records (INDEX §2) for their origin and
  destination, so Smart Organization can later expand or re-sort them.

## 10. Safety

- **Rules never delete or modify sources.** The strongest action is `skip`/`exclude`; deletion stays
  gated behind CRITICAL_MASS §9's verified-move guards and is never triggered by a prompt rule.
- **Preview-first and reversible.** All `warn`/`block` decisions are shown and confirmed before any
  copy; remembered decisions are editable in the rules file and in Settings.
- **Conservative defaults.** When unsure, a rule prompts rather than auto-skips; only clearly
  low-value, clearly regenerable, or clearly junk folders auto-apply (`info`).
- **No external calls.** Signature detection and bundling use stdlib only; no network, no telemetry.

## 11. Build order

1. `engine/prompt_rules.py` — the rule model + loader (default set + user JSON), matchers for file
   and folder metrics, signature detection, complexity score. Pure engine, no Gtk; golden tests over
   a fixture tree (venv, node_modules, .git, huge folder, large file, FAT-limit, long path).
2. Wire rule evaluation into Critical Mass **Plan**; emit coalesced hits; record decisions in the
   catalog; make resume read them.
3. `bundle`/`preserve-tree`/`quarantine` executors (stdlib `tarfile`/`zipfile`; verified like copies).
4. UI: the preview **Review panel** (coalesced prompts, per-rule bulk actions, remember), large-file
   time estimates, and a Settings editor for the rules file. Icons from the local Phosphor set.
5. Docs, changelog, decision record, change manifest; user strings via `_()`.

## 12. Roadmap placement

Tracked in `.claude/memory/pending.md` under Critical Mass: the **Prompt Rules** engine (size/
folder-size/complexity/signature triggers → predesignated actions, coalesced prompts, remembered
decisions), landing with Critical Mass's Plan/preview.

## 13. Open questions

- **Ship-defaults scope.** Is the default set in §6 the right starting list, and should any `warn`
  rules (e.g. `node_modules`) default to silent `info`-skip instead of prompting the first time?
- **Bundle format.** `.tar` (fast, POSIX-preserving) vs `.zip` (portable, browsable) as the default
  for `bundle` — and should bundles be compressed (CPU/time cost) or stored?
- **Thresholds.** Defaults (512 MiB / 4 GiB / 5 GiB / 50k files / depth 12) — confirm against real
  drives; make them per-destination aware?
- **`.git` handling.** Default to skipping only `.git/` while keeping the working tree, or offer
  "bundle the whole repo to preserve history" as the default for developer sources?
- **Learned suppression.** Should "remember" be per-rule global, or scoped to a source/drive so a
  skip remembered for one project does not silence another?
