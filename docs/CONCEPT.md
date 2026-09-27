# LinFileCopy — Technical Concept

> Status: **Implemented (v0.1.0)** · Concept version 0.2 · 2026-09-27
> As-built notes and deviations: [ARCHITECTURE.md](ARCHITECTURE.md)
> Scope: how the application is built, in what order, and which icons it uses.
> Mockups: [`docs/mockups/`](mockups/index.html)

### Changes in 0.2

- **Local storage only.** Cloud remotes, rclone, SSH and all network transport are removed.
  Supported storage: internal disks, removable drives (USB sticks, external SSD/HDD, SD
  cards) and local storage arrays (md RAID, LVM, btrfs/ZFS pools, DAS enclosures).
- **Engine: rsync only.** Two-way sync is implemented natively instead of with rclone bisync.
- Features that assumed a network were redefined for local drives: **#6** speed limit and
  I/O priority, **#10** encrypted drives (LUKS), **#13** native two-way sync, **#20**
  drive-aware endpoints. **#9 compression was dropped**, because rsync never compresses a
  local-to-local copy.
- New local-storage behaviour: jobs identify drives by filesystem UUID, adjust to each
  filesystem's limits (exFAT/FAT32/NTFS), check free space first, can eject when done,
  and can run when a drive is plugged in.

---

## 1. Product summary and tech stack

**LinFileCopy** is a native GTK 3 + Python desktop dashboard for building, running,
monitoring and scheduling copy and sync jobs between local disks and attached drives. It is
powered by **rsync**. The user never has to type a command. The exact command is always
shown so it can be checked and copied.

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.10+ (3.12 verified) | full type hints, dataclasses |
| UI toolkit | GTK 3.24 via PyGObject | pure-Python UI code, CSS styling (Adwaita-like), light and dark |
| Platform services | GLib / Gio | threads → `GLib.idle_add`, `Gio.Notification`, `Gio.VolumeMonitor`, `Gio.DBusProxy`, `Gio.Resource` |
| Drive management | UDisks2 over D-Bus (through Gio) | mount, unlock LUKS, unmount, power off. UDisks2 ships with every mainstream desktop |
| Copy engine | system `rsync` (3.2.7 here) | the only transfer tool. `ionice`/`nice` for background priority |
| Two-way sync | native Python + rsync | state stored in sqlite; see #13 |
| File watching | Linux inotify through `ctypes` | no pyinotify/watchdog |
| Atomic swap | `renameat2(RENAME_EXCHANGE)` through `ctypes` | |
| Storage | `json`, `sqlite3` | XDG directories |
| Scheduling | systemd user timers; crontab fallback | headless `linfilecopy run <job>` |
| i18n | `gettext` | |
| Tests | `unittest` (stdlib) | engine and model tested without a display |
| Optional | AyatanaAppIndicator3 (tray), libsecret (remember drive passphrases) | detected at runtime |
| Packaging | `pyproject.toml` (setuptools), `.desktop`, AppStream metainfo, Flatpak manifest, Debian `control`/`rules` | no pip runtime dependencies |

| Item | Value |
|---|---|
| Name | LinFileCopy |
| Application ID | `io.github.mensuramedia.LinFileCopy` |
| Python package | `linfilecopy` |
| Executable | `linfilecopy` (GUI) · `linfilecopy run <job>` (headless) |

## 2. Build philosophy (mandatory)

1. **No external dependencies at runtime.** The app uses only the Python standard library,
   PyGObject/GTK 3 and system tools (`rsync`, `ionice`, UDisks2). There are no pip
   packages, web fonts, CDNs or downloaded assets.
2. **All iconography is embedded.** Every icon comes from the local Phosphor set at
   `/home/user/projects/assets/Icons/phosphoricons` (v2.0.8, MIT). Icons are vendored into
   the repo and compiled into the app's GResource bundle. The app never loads icons from the
   system theme. See §7.
3. **Local storage only.** There is no network code path. Destinations are directories on
   mounted local filesystems.
4. **Optional integrations degrade gracefully.** A missing tray library, keyring or systemd
   is detected, and the affected feature is shown **disabled with the reason**. If rsync is
   missing, the app shows install instructions and stays usable for editing jobs.
5. **The GTK main loop never blocks.** Subprocesses, directory scans, UDisks calls and disk
   reads run on worker threads or through Gio async calls.
6. **Safety first.** Preview (dry run) is on by default for new jobs. Deletes need explicit
   confirmation with the number of files. Two-way sync moves deleted and overwritten files
   to a recoverable `.lfc-trash/` folder instead of erasing them.
7. **The engine is testable without a display.** `model/` and `engine/` never import `Gtk`.

### Environment detected on the dev machine (2026-09-27)

| Item | Status |
|---|---|
| rsync 3.2.7 | present |
| UDisks2 (system bus) | present |
| ionice, nice | present |
| AyatanaAppIndicator3, libsecret | present |
| systemd user session, crontab | present |
| Example drives | internal: 2 NVMe (ext4, several mounts); removable: 62 GB **exFAT** USB stick at `/media/user/B49B-37C5` |

## 3. Architecture

A Model–Engine–View split. Events flow **Engine → UI only through `GLib.idle_add`**.

```
┌──────────────────────────── UI (GTK 3) ────────────────────────────┐
│ window · sidebar · pages/* · widgets/*                              │
└──────────────▲────────────────────────────────────────┬─────────────┘
    idle_add   │ RunEvent(progress/log/state)           │ SyncJob
┌──────────────┴─────────── Engine (no Gtk) ─────────────▼─────────────┐
│ drives (UDisks2, fs capabilities) → planner → rsync_builder          │
│ → CommandPlan[steps] → runner (process group, pause/cancel, retry)   │
│ parsers (progress2 / itemize / stats)                                │
│ strategies: atomic · snapshots · parallel · twoway · watcher         │
│ scheduler (systemd --user / crontab / drive-connected) · notifier    │
└──────────────▲───────────────────────────────────────────────────────┘
┌──────────────┴──────────── Model (no Gtk) ───────────────────────────┐
│ SyncJob dataclasses · validation · templates · JobStore (JSON)       │
│ HistoryStore (sqlite3) · TwoWayState (sqlite3) · Settings            │
└──────────────────────────────────────────────────────────────────────┘
```

### File layout

```
linfilecopy/
├── pyproject.toml  README.md  CHANGELOG.md  LICENSE
├── linfilecopy/
│   ├── __init__.py  __main__.py
│   ├── app.py                  # Gtk.Application, actions, accelerators, single instance
│   ├── cli.py                  # headless: run / list / validate / preview
│   ├── i18n.py  paths.py  resources.py
│   ├── model/
│   │   ├── enums.py            # Mode, OverwritePolicy, ConflictPolicy, DriveKind, …
│   │   ├── job.py              # SyncJob + nested option dataclasses
│   │   ├── validation.py       # Issue(level, field, message, fix)
│   │   ├── templates.py  store.py  history.py
│   ├── engine/
│   │   ├── tools.py            # detect rsync version/capabilities, ionice, systemd
│   │   ├── drives.py           # UDisks2: list, resolve UUID→mount, mount, unlock, eject
│   │   ├── filesystems.py      # capability table per fs type → flag adjustments
│   │   ├── planner.py          # SyncJob → CommandPlan (ordered steps)
│   │   ├── rsync_builder.py    # pure: options → argv
│   │   ├── runner.py           # JobRunner thread; pause/resume/cancel; retries
│   │   ├── progress.py  exitcodes.py
│   │   ├── atomic.py  snapshots.py  parallel.py
│   │   ├── twoway.py           # native bidirectional sync (scan, diff, resolve, apply)
│   │   ├── filtermatch.py      # rsync-pattern matcher used by twoway + filter test
│   │   ├── watcher.py          # inotify via ctypes, debounce
│   │   ├── scheduler.py        # systemd timers, crontab, drive-connected triggers
│   │   └── notify.py
│   ├── ui/
│   │   ├── window.py  icons.py
│   │   ├── pages/{dashboard,designer,transfers,history,scheduler,settings}.py
│   │   └── widgets/{path_field,drive_picker,feature_row,filter_editor,command_preview,
│   │                progress_card,stat_tile,confirm_dialog,passphrase_dialog}.py
│   └── data/
│       ├── linfilecopy.gresource.xml  style.css  style-dark.css
│       ├── icons/scalable/actions/lfc-*-symbolic.svg   # vendored Phosphor
│       ├── icons/ICONS.md  icons/LICENSE-phosphor
│       ├── app-icon/…  templates/*.json
├── tools/  vendor_icons.py  icons.manifest  build_resources.sh  build_mockups.py
├── tests/  po/  packaging/{desktop,metainfo,flatpak,debian}/  docs/
```

## 4. The job model

```python
@dataclass
class SyncJob:
    id: str; name: str; description: str = ""
    source: Endpoint; destination: Endpoint          # B1, #20
    mode: Mode = Mode.COPY                           # B2, #2, #13: COPY | MIRROR | TWO_WAY
    overwrite: OverwritePolicy = OverwritePolicy.ALWAYS   # B9
    preview_first: bool = True                       # B7, #4
    transfer: TransferOptions      # #1 delta/inplace/whole-file, #2 compare method,
                                   # #7 resume, #8 checksum, #15 sparse
    performance: PerformanceOptions  # #6 speed limit + io priority, #12 parallel streams
    metadata: MetadataOptions      # B5, #3
    filters: FilterOptions         # B6, #5
    safety: SafetyOptions          # #16 atomic, #17 snapshots
    twoway: TwoWayOptions          # #13 conflict policy, trash, max-delete guard
    drive: DriveOptions            # #10 unlock encrypted, #20 eject/lock after, wait for drive
    triggers: TriggerOptions       # #14 on file change, on drive connected
    logging: LoggingOptions        # #18
    schedule: ScheduleOptions      # #19
    schema_version: int = 2

@dataclass
class Endpoint:
    path: str                      # absolute path as last seen
    volume_uuid: str | None        # filesystem UUID when on a non-root volume
    volume_label: str | None       # for display: "62 GB Volume", "Archive"
    relative_path: str | None      # path inside the volume, so a changed mount point still works
    kind: DriveKind                # INTERNAL | REMOVABLE | ARRAY (detected, informational)
```

At run time `drives.resolve(endpoint)` finds the current mount point for `volume_uuid`.
If the drive is connected but not mounted, it is mounted through UDisks2. If it is not
connected, the run fails with "Connect *Archive* and try again", or waits when "Wait for
drive" is on.

## 5. Build order (precedence)

The order follows three rules. (a) Nothing is built before the thing it depends on.
(b) The ten **basic features (B1–B10)** make a usable product first. (c) Advanced features
come afterwards, starting with the ones that are only flags and ending with the ones that
need their own strategies. Every phase ends with passing tests and a commit and push to
`origin/main`.

| Phase | Deliverable | Features | Exit criteria |
|---|---|---|---|
| **P0 Foundation** | package skeleton, `paths`, `i18n`, logging, icon vendoring + GResource, CSS, window with sidebar/stack, tool detection | — | app launches; icons are embedded; rsync detected |
| **P1 Model** | `SyncJob` + enums, JSON with schema version, validation, templates, JobStore | data for all features | round-trip tests |
| **P2 Drives + builder** | `drives.py` (UDisks2 list/resolve/mount), `filesystems.py`, `rsync_builder`, `planner`, command preview | B1 B2 B5 B6 B7 B9 · #1–#8 #15 #20 | golden tests per feature and per filesystem type (ext4, exfat, vfat, ntfs) |
| **P3 Runner + progress** | subprocess in a process group, parsers, pause/cancel, exit-code mapping, retries, free-space preflight | B3 B4 · #11 #18 | integration test: real rsync between temp dirs, and onto a loop-mounted exFAT image |
| **P4 MVP UI** | Designer *Simple*, Transfers, preview dialog, History with re-run, notifications, delete confirmation, drive picker, eject | **B1–B10 complete** | a basic job to a USB stick can be designed, previewed, run, paused, cancelled, re-run and ejected |
| **P5 Advanced designer** | *Advanced* view, live command preview, copy command, drag and drop, templates | #1–#8 #12 #15 #20 in the UI | every control changes the preview |
| **P6 Strategies** | atomic replace, snapshots + rotation, parallel, LUKS unlock, **native two-way**, inotify watcher | #10 #12 #13 #14 #16 #17 | tests for each strategy on temp dirs |
| **P7 Scheduling & triggers** | `cli.py run`, systemd timers, crontab fallback, drive-connected trigger, Scheduler page | #14 #19 | timer create/list/toggle/remove; plugging in a drive runs its job |
| **P8 Polish** | tray, shortcuts, accessibility, dark mode, responsive layout, gettext template | — | accessibility checklist passes; no main-loop stall > 50 ms |
| **P9 Packaging** | desktop file, metainfo, app icon PNGs, Flatpak, Debian, README, DEVELOPER.md | — | `pip install .` and `dpkg-buildpackage -b` succeed |

Two-way sync (#13) is the largest single piece of work now, because it is built natively.
It is scheduled in P6, after the runner and filter matcher it depends on are stable.

## 6. Feature → implementation map

### 6.1 Basic features (B1–B10) — *Simple* view

| # | Feature | UI | rsync | Notes |
|---|---|---|---|---|
| B1 | Source & destination | two `PathField`s: drop target, Browse, **drive picker** (lists internal, removable and array volumes with label, fs type and free space), swap button | positional args; "copy the folder itself / its contents" toggle controls the trailing `/` | drag and drop accepts `text/uri-list`; source blue, destination green |
| B2 | Copy vs Sync (mirror) | segmented **Copy · Mirror · Two-way** | Mirror → `--delete-delay` | Mirror always confirms with a count from a dry run |
| B3 | Progress, speed, ETA | progress card | `--info=progress2,name1,stats2 --outbuf=L` | parsed at most 4 times per second |
| B4 | Start / Pause / Cancel | primary Start + Pause/Cancel | SIGSTOP/SIGCONT/SIGTERM to the process group | unplugging a drive mid-run → clear "drive removed" error; resume later from partials |
| B5 | Preserve dates & permissions | one checkbox, on by default | `-rlptD` | auto-reduced for exFAT/FAT (see §6.3) and explained in the UI |
| B6 | Skip common items | preset chips + custom | `--exclude` | presets: hidden, caches, temp, system (`lost+found/`, `.Trash-*/`, `System Volume Information/`, `$RECYCLE.BIN/`, `.Spotlight-V100/`) |
| B7 | Preview | Preview button + "Always preview first" | `--dry-run --itemize-changes` | list of create/update/delete with filters |
| B8 | Job history | History page with Re-run | — | sqlite `runs` table |
| B9 | Existing files | Overwrite · Skip · Overwrite if newer | default · `--ignore-existing` · `--update` | on FAT/exFAT "newer" uses `--modify-window=1` |
| B10 | Finish notification | switch (on) | — | `Gio.Notification`; offers **Eject** when the destination is removable |

### 6.2 Top-20 features — *Advanced* view

| # | Feature | UI | Implementation | Constraints & validation |
|---|---|---|---|---|
| 1 | Delta transfer | switch + "Update in place", "Whole files" | rsync uses whole-file by default for local copies, because delta costs more than it saves on local disks. Delta on → `--no-whole-file`; `--inplace`; `-W` | tooltip explains when delta helps locally (large files, slow USB destination) |
| 2 | Incremental sync | "Decide what changed by": size+time / size only / checksum | default · `--size-only` · `-c` | |
| 3 | Metadata | checkboxes: permissions, owner, group, times, ACLs, xattrs, hard links, devices | `-p -o -g -t -A -X -H -D` | limited by the destination filesystem (§6.3). Owner/group need root → warning |
| 4 | Dry run | Preview toggle in the header bar + Preview button | `-n -i` | |
| 5 | Filters | ordered rule list, add/remove/move, exclude-from, files-from, **Test** | `--include`/`--exclude`, `--exclude-from`, `--files-from` | Test = dry run showing matched paths |
| 6 | **Speed limit & priority** | "Limit speed" (MB/s) + "Run in background priority" | `--bwlimit=<KiB>`; wrap in `ionice -c3 nice -n 19` | keeps the desktop responsive and protects slow USB sticks |
| 7 | Resume | "Resume interrupted files" | `--partial --partial-dir=.lfc-partial` | partial dir excluded from mirror deletes |
| 8 | Checksum | "Verify with checksums" | `-c` | |
| 9 | ~~Compression~~ | **removed** | rsync does not compress local copies | — |
| 10 | **Encrypted drives** | "Unlock encrypted drive before running" + "Lock after job"; passphrase dialog, optional "remember in keyring" | UDisks2 `Encrypted.Unlock` → `Filesystem.Mount`; after the job `Unmount` → `Encrypted.Lock` | scheduled runs need a remembered passphrase or an already unlocked drive; the validator warns |
| 11 | Progress & stats | Transfers page: bar, current file, speed graph, ETA, counts; stats pane | parsed `progress2` + `stats2` | stored in history |
| 12 | Parallel transfers | "Parallel streams" 1–16 | split top-level entries into N balanced buckets → N rsync processes with `--files-from`; progress aggregated | tooltip: helps NVMe/arrays, slows single USB sticks and HDDs. Disabled with #16/#17 in v1 |
| 13 | **Two-way sync (native)** | mode **Two-way** + conflict policy: newer wins · larger wins · keep both (rename loser) · source wins · ask; "Keep deleted files in .lfc-trash" (on); delete guard % | see §6.4 | first run merges both sides and shows a preview |
| 14 | Real-time sync | "Run when files change" + watch list + delay | inotify via `ctypes`, recursive, debounce | runs while the app or tray is alive |
| 15 | Sparse files | switch | `-S` | |
| 16 | Atomic replace | "Atomic replace (all-or-nothing)" | rsync into `<dest>.lfc-stage` with `--link-dest=<dest>`, then `renameat2(RENAME_EXCHANGE)`, then remove the old tree | stage must be on the same filesystem (always true); needs free space for changed files; not on FAT/exFAT (no hard links) |
| 17 | Snapshots | switch + keep daily/weekly | `dest/<YYYY-mm-ddTHHMMSS>` + `--link-dest=../latest`, `latest` symlink, rotation | needs hard links and symlinks → ext4/xfs/btrfs/ZFS/NTFS only, disabled on exFAT/FAT |
| 18 | Logging & errors | log level, notify on failure/success, retries | `--log-file` + stderr; exit-code map | retry only on transient codes (10, 11, 12, 23, 30) |
| 19 | Scheduling | Once · Hourly · Daily · Weekly · Custom (cron) · **When drive connected** | systemd user timer / crontab; drive trigger via `Gio.VolumeMonitor` `mount-added` matched by UUID | drive trigger runs while the app or tray is alive |
| 20 | **Drive-aware endpoints** | drive picker; drive info (label, fs, free space, removable); "Eject when finished"; "Wait for drive" | UUID-based resolution (§4); fs capability adjustment (§6.3); free-space preflight | internal, removable and array volumes; arrays are ordinary mount points |

### 6.3 Filesystem capability table

`filesystems.py` reads the destination fs type from UDisks2 (or `/proc/self/mountinfo`) and
adjusts the plan. Every automatic change is listed in the designer ("Adjusted for exFAT: …").

| Filesystem | Perms / owner | Symlinks | Hard links | ACL / xattr | Time precision | Other |
|---|---|---|---|---|---|---|
| ext4, xfs, btrfs, ZFS, f2fs | yes | yes | yes | yes | ns | — |
| NTFS (ntfs3) | no (mapped) | yes | yes | no | 100 ns | — |
| exFAT | no → drop `-p -o -g` | no → choice: follow (`-L`) or skip (`--no-links`) | no | no | 2 s → `--modify-window=1` | — |
| FAT32 (vfat) | no | no | no | no | 2 s | **4 GiB file limit** → preflight lists oversize files; names are case-insensitive → collision warning; reserved characters `" * : < > ? \|` → warning |

### 6.4 Native two-way sync (#13)

1. **State**: `$XDG_DATA_HOME/linfilecopy/state/<job-id>.sqlite` stores `(relpath, type, size, mtime_ns)`
   from the last successful sync, when both sides matched.
2. **Scan** both sides with `os.scandir` on a worker thread, applying the job's filters through
   `filtermatch.py` (the rsync pattern subset the UI can produce, tested against
   `rsync --list-only` output).
3. **Classify** each path against the state: unchanged, changed on A, changed on B, changed on
   both (conflict), deleted on A or B, new on one side, new on both (conflict if different).
   Timestamps are compared with the destination filesystem's precision.
4. **Resolve** conflicts with the policy. "Keep both" renames the loser to
   `name.conflict-<host>-<date>.ext`. "Ask" stops before any change and shows the list.
5. **Guard**: abort if more than the delete-guard percentage (default 50%) of files would be
   deleted on either side. This protects against an empty or wrongly mounted drive.
6. **Apply**: copies go through rsync with `--files-from` in each direction (so progress
   parsing is reused). Deletions and overwritten files move to `<root>/.lfc-trash/<timestamp>/`
   on the same drive.
7. **Commit** the new state only after both directions succeed. An interrupted run leaves
   the old state in place and is safe to repeat.

### 6.5 Progress parsing contracts

- `--info=progress2`: `^\s*([\d,]+)\s+(\d+)%\s+(\S+/s)\s+(\d+:\d{2}:\d{2})(?:\s+\(xfr#(\d+), (?:ir|to)-chk=(\d+)/(\d+)\))?`
- `name1` lines (no percentage) set `current_file`.
- `-i` preview: `^([<>ch.*][fdLDS][cstpoguax.+ ]{9})\s(.+)$` and `^\*deleting\s+(.+)$`.

### 6.6 Exit-code mapping (excerpt)

| rsync | Meaning shown | Suggested fix |
|---|---|---|
| 3 | Error selecting files | Check that the source folder exists and is readable |
| 11 | File I/O error | The drive may be full, read-only or disconnected. Check free space and reconnect it |
| 12 | Data stream error | Usually a drive that was removed during the copy. Reconnect it and run again (resume picks up partial files) |
| 23 | Some files failed | Open the log. Usually permission denied, or names/sizes the destination filesystem cannot store |
| 24 | Source files vanished | Usually harmless; files changed during the copy |
| 20 | Stopped | You cancelled the job, or the system shut down |

## 7. Iconography

### 7.1 Embedding pipeline

1. `tools/icons.manifest` lists every icon the app uses: `semantic-id  phosphor-name  weight  purpose`.
2. `tools/vendor_icons.py` copies each one into
   `linfilecopy/data/icons/scalable/actions/lfc-<id>-symbolic.svg` and checks `fill="currentColor"`.
   It also copies Phosphor's LICENSE. Vendored SVGs are **committed**, so builds never need the asset directory.
3. `build_resources.sh` compiles the icons and CSS into `linfilecopy.gresource`.
4. `resources.py` registers the bundle and calls `Gtk.IconTheme.add_resource_path(...)`.
5. `ui/icons.py`: `icon("action-start", Gtk.IconSize.BUTTON)`. The `lfc-` prefix prevents
   collisions with system theme icons. The `-symbolic` suffix lets GTK recolour icons for
   light and dark themes.

### 7.2 Weights and sizes

| Context | Size | Weight |
|---|---|---|
| Sidebar | 20 px | regular; **fill** when selected |
| Buttons, header bar, rows | 16 px | regular |
| Primary Start | 16 px | fill |
| Status badges | 16 px | fill (bold for spinner/cancelled) |
| Stat tiles | 32 px | duotone |
| Empty states | 64 px | light |

### 7.3 Icon map

The authoritative list is `tools/icons.manifest`. The mockups include a generated legend.
The main choices:

| Group | Choices |
|---|---|
| Navigation | Dashboard `squares-four` · Designer `sliders-horizontal` · Transfers `pulse` · History `clock-counter-clockwise` · Scheduler `calendar-check` · Settings `gear-six` |
| Job control | Start `play` (fill) · Pause `pause` · Cancel `stop` · Preview `eye` · Run again `arrow-clockwise` · Retry `arrow-counter-clockwise` · Save `floppy-disk` · Copy command `clipboard-text` · Browse `folder-open` · Swap `arrows-down-up` · Templates `stack` |
| Drives | Internal disk `hard-drive` · Removable drive `usb` · Storage array `hard-drives` · Eject `eject` · Encrypted `lock-key` · Unlock `lock-simple-open` · Drive connected trigger `plug` · Drive not connected `plugs` · Passphrase `password` |
| Modes | Copy `arrow-right` · Mirror `arrows-clockwise` · Two-way `arrows-left-right` · Conflict `scales` · Overwrite `swap` · Skip `skip-forward` · If newer `clock-clockwise` |
| Features | Delta `git-diff` · Compare `list-checks` · Metadata `tag` · Filters `funnel` · Speed `gauge` · Priority `feather` · Resume `play-pause` · Checksum `fingerprint` · Stats `chart-line-up` · Parallel `rows` · Real-time `lightning` · Sparse `file-dashed` · Atomic `atom` · Snapshots `camera` · Logging `scroll` · Notify `bell` · Schedule `calendar-check` · Trash `trash` |
| Status | running `circle-notch` · paused `pause-circle` · success `check-circle` · warning `warning-circle` · failed `x-circle` · cancelled `prohibit` · scheduled `clock` · queued `hourglass` |

**App icon**: rounded tile with Phosphor `copy`, built from the local SVG and exported to PNG
16–512 px with GdkPixbuf at build time.

## 8. UI concept

- **Window**: HeaderBar (New job, Templates, Preview mode, main menu) with a 212 px sidebar
  and a `Gtk.Stack`. The sidebar footer lists **connected drives** with free space and an eject
  button. Below 900 px the sidebar shows icons only. Below 640 px it becomes a menu.
- **Designer**: form on the left, sticky command preview and validation on the right
  (stacked when narrow), and a *Simple / Advanced* switch.
- **Source vs destination**: blue FROM card and green TO card, each with a drive badge
  (label · filesystem · free space).
- **Destructive actions**: Mirror shows a warning. Start confirms with the delete count.
  Two-way shows the trash location.
- **Theme**: follows the desktop's dark preference; CSS colour tokens with a dark variant.

### Keyboard shortcuts

| Keys | Action | | Keys | Action |
|---|---|---|---|---|
| Ctrl+N | New job | | Ctrl+S | Save job |
| Ctrl+Return | Start | | Ctrl+Shift+P | Preview |
| Space (Transfers) | Pause/Resume | | Escape (Transfers) | Cancel (asks first) |
| Ctrl+Shift+C | Copy command | | Ctrl+1…6 | Switch page |
| Ctrl+E | Eject destination drive | | Ctrl+? | Shortcuts window |

## 9. Persistence

| Data | Location | Format |
|---|---|---|
| Jobs | `$XDG_CONFIG_HOME/linfilecopy/jobs/<id>.json` | JSON, `schema_version` |
| Settings | `$XDG_CONFIG_HOME/linfilecopy/settings.json` | JSON |
| History | `$XDG_DATA_HOME/linfilecopy/history.db` | sqlite3 |
| Two-way state | `$XDG_DATA_HOME/linfilecopy/state/<job-id>.sqlite` | sqlite3 |
| Run logs | `$XDG_STATE_HOME/linfilecopy/logs/<run-id>.log` | text, removed after 90 days |
| Drive passphrases | libsecret (optional, opt-in per drive) | never in JSON |

## 10. Open points for review

1. **#9 Compression was dropped.** It has no effect on local copies. The alternative is
   "compressed archive output" (tar.zst), which is a different feature and is not planned.
2. **#10 now covers encrypted drives (LUKS).** Veracrypt and other containers are out of scope.
3. **#13 two-way sync is native Python.** It is the largest custom component and needs the
   most tests. The alternative would be to require `unison`, which is not installed.
4. **Drive-connected triggers and real-time watching** only work while the app or tray is running.
5. **Flatpak** needs `--filesystem=host`, `--system-talk-name=org.freedesktop.UDisks2` and
   `flatpak-spawn --host` for scheduling. A native Debian package is simpler for this app.
6. The reference repositories have not been reviewed yet (the fetch was stopped).
