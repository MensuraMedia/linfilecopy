# LinFileCopy — Handoff

**Last updated:** 2026-10-05
**Repo:** https://github.com/MensuraMedia/linfilecopy (default branch `main`, HEAD `e0a36d3`)
**Status:** v0.1.0 shipped and packaged (157 tests passing). Actively designing a
**"Capture & Organize" feature suite** — five concept docs landed, none implemented yet.
**Owner:** MensuraMedia (`lin-*` desktop app series).

This is the practical "pick it up and keep going" document. Design rationale is in
`docs/CONCEPT.md`; as-built details in `docs/ARCHITECTURE.md`; dated history in `changelog.md`;
invariants in `CLAUDE.md` and `.claude/rules/`; the roadmap in `.claude/memory/pending.md`.

---

## 1. What it is

A native GTK 3 + PyGObject desktop dashboard for building, running, monitoring and scheduling
**copy/sync jobs** between local disks and attached drives, powered by **rsync**. Hard constraints
(non-negotiable — see `CLAUDE.md`): **no external runtime dependencies** (stdlib + PyGObject +
system tools only), **local storage only** (no cloud/SSH), **all icons embedded from the local
Phosphor set**.

## 2. Run / build / test

```bash
python3 -m linfilecopy                      # GUI
python3 -m linfilecopy run <job>            # headless
python3 -m unittest discover -s tests       # 157 tests, no display needed
xvfb-run -a python3 -m unittest tests.ui_smoke   # UI smoke (needs a display)
python3 tools/vendor_icons.py && tools/build_resources.sh   # after icon/CSS edits
tools/build_deb.sh ; ./install.sh           # package + install (apt; ./install.sh --user elsewhere)
```

Live display here is Cinnamon/X11 on `DISPLAY=:0`. Use `LFC_NON_UNIQUE=1` for screenshots/tests
so they never hand off to a running instance. Screenshot tool: `tools/screenshot.py`.

## 3. Architecture (one-way layering)

**Model–Engine–View.** `linfilecopy/model` (dataclasses, stores) and `linfilecopy/engine`
(rsync builder/runner, strategies, two-way sync) **must not import Gtk/Gdk**; `linfilecopy/ui`
(GTK) receives engine events **only through `GLib.idle_add`**. rsync is the sole transfer engine;
every flag comes from `engine/rsync_builder.py` with a golden test. Naming (from
gtk-python-dashboard-starter): `page_*.py`→`*Page(BasePage)`, `component_*.py`→`*Widget`,
`manager_*.py`→`*Manager`, `on_*` handlers.

## 4. Current status

- **Shipped (v0.1.0):** full Designer / Transfers / History / Dashboard / Quick View / Scheduler /
  Settings; rsync builder + runner; native two-way sync; snapshots; drive management (UDisks2);
  inotify + drive-connected triggers; Ayatana tray; systemd/cron scheduling; Debian package +
  installers; 157 tests.
- **Most recent code change:** compact Cairo **`ProgressRing`** added to Active-Transfers run cards
  (`ui/components/component_run_card.py`, commit `301bc56`) — reused by the proposed features below.
- **In design (not implemented):** the Capture & Organize concept suite (§5).

## 5. The "Capture & Organize" concept suite (design-stage)

Five cross-linked concept docs, all **Proposed / not implemented**. Read in this order:

1. **`docs/CRITICAL_MASS.md`** (v0.3) — a new page for **aggressive multi-source capture**: scan any
   list of sources (drives/mountpoints/folders), identify every file (extension + content sniff),
   copy type-sorted into `dest/files_<category>/files_<subtype>/…` (one folder per type, subtype
   subfolders), with a durable `_catalog/`. Covers the full verified-move lifecycle: duplicate-name
   handling (§5, `MyFile_copy_01.ext`), end-to-end sha256 **verification** + confirmation gate (§8),
   **interruption-tolerant resume** (per-file state machine, rsync `--partial`/`--append-verify`,
   drive-disconnect pause/resume) (§7), and opt-in **verified-move delete** of sources only after
   100% confirmation (§9).
2. **`docs/CRITICAL_MASS_PROMPT_RULES.md`** — a **data-driven rule engine** run at Plan time that
   prompts for a predesignated action (include/preserve-tree/bundle/quarantine/skip/…) by **file
   size**, **folder size**, **folder complexity/file-count**, and **folder signature** (e.g. a
   `venv`, `node_modules`, `.git`, build/cache dirs). Coalesced prompts, remembered decisions; a
   skip never deletes.
3. **`docs/DUPLICATES.md`** — a **Duplicates** page: point at a folder, hash every file (tiered
   size→prefix→SHA-256→byte-verify, **stdlib `hashlib` only**, borrowing LinFileDedup's engine),
   index per-file results, and report **exact 1-to-1 duplicates** plus **same-name/different-content
   name conflicts** (→ `_copy_NN` rename). All types by default + ignore-type options; **net-new
   large-file time-table/ETA** (LinFileDedup projects none). Backs Critical Mass's dedup pass.
4. **`docs/INDEX_AND_SMART_ORGANIZATION.md`** — a **persistent cross-run Index** that Critical Mass
   writes on every run (origin path+drive ⇄ destination path incl. `_copy_NN`, keyed by sha256 with
   full lineage), powering a future **Smart File Organization** (index-driven re-sort, global dedup,
   reconstruct-original-view, undo) and **Smart-Link** (hard-link same-fs = inode re-designation /
   symlink cross-fs, index-maintained self-healing, so other apps still reach moved files).

**How they fit together:** Critical Mass is the spine. Prompt Rules gate its Plan stage; Duplicates
is its dedup detector and shares the hash index; the Index records everything it places and later
feeds Smart Organization + Smart-Link. All stay within LinFileCopy's rules (rsync engine for copies,
stdlib-only, engine Gtk-free, `GLib.idle_add`, reuse of the existing `ProgressRing` and run cards).

## 6. Suggested implementation order (when building begins)

1. `engine/hashindex.py` — the persistent `(dev,ino,size,mtime)→(prefix,sha256)` cache, shared by
   Duplicates and the global Index. (DUPLICATES §5, INDEX §2.)
2. `engine/duplicates.py` + `page_duplicates.py` — smallest self-contained feature; proves hashing,
   the ETA/time-table, and `ProgressRing` reuse. (DUPLICATES.)
3. `engine/catalog.py` (WAL state machine) + `engine/prompt_rules.py` — the Critical Mass spine and
   its rule engine. (CRITICAL_MASS §5–§9, PROMPT_RULES.)
4. `engine/critical_mass.py` + `page_critical_mass.py` — scan→classify→rules→plan→copy(rsync)→
   verify→[reclaim], writing Index records on every run.
5. `engine/smartlink.py` + `engine/smart_organize.py` — advanced/future, capability-gated.

Each step: golden/engine tests first (no display), then UI, then changelog + decision + change
manifest + memory, then commit & push per the per-feature convention.

## 7. Related project — orico-keepalive

`/home/user/projects/orico-keepalive` (keeps the Orico USB bay awake; see memory
`external-drives-and-keepalive`). It is a **local git repo** (commit `3d26cd5`, branch `main`) that
is **not yet pushed** — creating its GitHub repo is a deliberate **backlog** item (`BACKLOG.md`
there), per the owner. Its `docs/CONCEPT.md` generalises the keepalive to all connected storage;
that generalisation is also backlog, not built.

## 8. Invariants & conventions (don't break)

- No external runtime deps; local storage only; icons only from the local Phosphor set (via
  `tools/icons.manifest`). `model/` + `engine/` never import Gtk; UI updates via `GLib.idle_add`.
- Safety-first: preview/dry-run default, confirm deletes with counts, two-way uses `.lfc-trash`;
  never build shell strings (argv lists, `shell=False`); validate paths; parameterised sqlite.
- Per change: update `changelog.md` (ISO 8601), write a change manifest in `.claude/memory/changes/`,
  record decisions in `.claude/memory/decisions.md`, keep `MEMORY.md` current, then commit & push to
  `origin/main`.

## 9. Pointers

- Design: `docs/CONCEPT.md` · as-built: `docs/ARCHITECTURE.md` · dev: `docs/DEVELOPER.md` ·
  mockups: `docs/mockups/index.html`
- Concept suite: the five docs in §5
- Roadmap / pending: `.claude/memory/pending.md` · decisions: `.claude/memory/decisions.md` ·
  history: `changelog.md` · change manifests: `.claude/memory/changes/`
- Rules: `.claude/rules/` (project-conventions, security, token-hygiene, memory-rules)
