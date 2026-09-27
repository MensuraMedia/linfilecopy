# LinFileCopy — Technical Concept

> Status: **Draft for review** · Version 0.1 · 2026-09-27
> Scope: how the application is built, in what order, and which icons it uses.
> Mockups: [`docs/mockups/`](mockups/index.html)

---

## 1. Product summary

**LinFileCopy** is a native GTK 3 + Python desktop dashboard for building, running,
monitoring and scheduling file copy and sync jobs. It uses **rsync** for local and SSH
work and **rclone** for cloud remotes. The user never has to type a command. The exact
command is always shown so it can be checked and copied.

| Item | Value |
|---|---|
| Name | LinFileCopy |
| Application ID | `io.github.mensuramedia.LinFileCopy` (reverse-DNS of the GitHub org) |
| Python package | `linfilecopy` |
| Executable | `linfilecopy` (GUI) · `linfilecopy run <job>` (headless, used by the scheduler) |
| Toolkit | GTK 3.24 via PyGObject, styled with bundled CSS (Adwaita-like) |
| Python | 3.10+ (3.12 verified) |

## 2. Build philosophy (mandatory)

1. **No external dependencies at runtime.** The app uses only the Python standard library,
   PyGObject/GTK 3 (the chosen toolkit) and the transfer tools it drives
   (`rsync`, optionally `rclone`/`unison`). There are no pip packages, web fonts, CDNs or
   downloaded assets.
2. **All iconography is embedded.** Every icon comes from the local Phosphor set at
   `/home/user/projects/assets/Icons/phosphoricons` (v2.0.8, MIT). Icons are vendored into
   the repo and compiled into the app's GResource bundle. The app never loads icons from
   the system theme, so it looks the same on GNOME, KDE, XFCE and Cinnamon. See §7.
3. **Optional integrations degrade gracefully.** Missing tools such as rclone, unison,
   AyatanaAppIndicator or libsecret are detected at start-up. Features that need them
   are shown **disabled with an explanation and install instructions**, never hidden and
   never allowed to crash.
4. **The GTK main loop never blocks.** Every subprocess, file-system scan and disk read
   happens on worker threads. Results return through `GLib.idle_add`.
5. **Safety first.** Preview (dry run) is on by default for new jobs. Anything that deletes
   files needs explicit confirmation that lists the number of files affected.
6. **The engine is testable without a display.** `model/` and `engine/` never import `Gtk`.
   The command builders are pure functions with golden-output unit tests (`unittest`,
   stdlib).

### Tooling detected on the dev machine (2026-09-27)

| Tool | Status | Impact |
|---|---|---|
| rsync 3.2.7 | present | primary engine |
| rclone | **missing** | cloud and bisync features show the "install rclone" state; tests use recorded fixtures |
| unison, lsyncd, inotifywait | missing | not required: bidirectional sync uses rclone bisync; the watcher uses inotify through `ctypes` |
| AyatanaAppIndicator3 | present | tray icon enabled when available |
| libsecret (gi `Secret`) | present | optional password storage; falls back to "ask each run" |
| glib-compile-resources | present | icon and CSS bundling |
| systemd user session, crontab | present | scheduler backends |

## 3. Architecture

A Model–Engine–View split. Signals and callbacks only ever flow **Engine → UI through
`GLib.idle_add`**.

```
┌──────────────────────────── UI (GTK 3) ────────────────────────────┐
│ window · sidebar · pages/* · widgets/*        (Controller glue)     │
└──────────────▲────────────────────────────────────────┬─────────────┘
    idle_add   │ RunEvent(progress/log/state)           │ SyncJob
┌──────────────┴─────────── Engine (no Gtk) ─────────────▼─────────────┐
│ planner → builders (rsync/rclone) → CommandPlan[steps]               │
│ runner (subprocess, process group, pause/cancel, retry)              │
│ parsers (rsync progress2 / itemize, rclone JSON stats)               │
│ strategies: atomic · snapshots · parallel · bisync · watcher         │
│ scheduler (systemd --user / crontab) · notifier · tools detection    │
└──────────────▲───────────────────────────────────────────────────────┘
               │
┌──────────────┴──────────── Model (no Gtk) ───────────────────────────┐
│ SyncJob dataclasses · validation · templates · JobStore (JSON)       │
│ HistoryStore (sqlite3) · Settings                                    │
└──────────────────────────────────────────────────────────────────────┘
```

### File layout

```
linfilecopy/
├── pyproject.toml              # setuptools, no runtime deps, package-data
├── README.md  CHANGELOG.md  LICENSE
├── linfilecopy/
│   ├── __init__.py  __main__.py
│   ├── app.py                  # Gtk.Application, actions, accelerators, single instance
│   ├── cli.py                  # headless: run / list / validate / preview
│   ├── i18n.py                 # gettext setup, _() helper
│   ├── paths.py                # XDG config/data/state dirs
│   ├── resources.py            # loads linfilecopy.gresource, registers icon path + CSS
│   ├── model/
│   │   ├── enums.py            # Mode, Protocol, OverwritePolicy, ConflictPolicy, …
│   │   ├── job.py              # SyncJob + nested dataclasses (all 20 + 10 features)
│   │   ├── validation.py       # returns Issue(level, field, message, fix)
│   │   ├── templates.py        # built-in templates
│   │   ├── store.py            # JobStore: ~/.config/linfilecopy/jobs/<id>.json
│   │   └── history.py          # HistoryStore: ~/.local/share/linfilecopy/history.db
│   ├── engine/
│   │   ├── tools.py            # detect rsync/rclone/unison versions & capabilities
│   │   ├── planner.py          # SyncJob → CommandPlan (ordered steps)
│   │   ├── rsync_builder.py    # pure: options → argv
│   │   ├── rclone_builder.py   # pure: options → argv
│   │   ├── runner.py           # JobRunner thread; pause/resume/cancel; retries
│   │   ├── progress.py         # line parsers → ProgressSnapshot
│   │   ├── exitcodes.py        # rsync/rclone code → message + suggested fix
│   │   ├── atomic.py           # staging + renameat2(RENAME_EXCHANGE)
│   │   ├── snapshots.py        # timestamped dirs, link-dest, rotation
│   │   ├── parallel.py         # split-and-fan-out rsync wrapper
│   │   ├── watcher.py          # inotify via ctypes, debounce
│   │   ├── scheduler.py        # systemd user timers + crontab backend
│   │   └── notify.py           # Gio.Notification wrapper
│   ├── ui/
│   │   ├── window.py           # HeaderBar + sidebar + Gtk.Stack
│   │   ├── icons.py            # icon("play", size) helper, name registry
│   │   ├── pages/{dashboard,designer,transfers,history,scheduler,settings}.py
│   │   └── widgets/{path_field,feature_row,filter_editor,command_preview,
│   │                progress_card,stat_tile,confirm_dialog,tool_missing_bar}.py
│   └── data/
│       ├── linfilecopy.gresource.xml
│       ├── style.css  style-dark.css
│       ├── icons/scalable/actions/lfc-*-symbolic.svg   # vendored Phosphor
│       ├── icons/ICONS.md  icons/LICENSE-phosphor
│       ├── app-icon/io.github.mensuramedia.LinFileCopy.svg (+ PNG 16…512)
│       └── templates/*.json
├── tools/
│   ├── vendor_icons.py         # copies icons listed in icons.manifest from the asset dir
│   ├── icons.manifest          # lfc-name  ←  phosphor-name  weight
│   └── build_resources.sh      # glib-compile-resources
├── tests/                      # unittest; no display needed for model/engine
├── po/                         # POTFILES.in, linfilecopy.pot
├── packaging/
│   ├── io.github.mensuramedia.LinFileCopy.desktop
│   ├── io.github.mensuramedia.LinFileCopy.metainfo.xml
│   ├── flatpak/io.github.mensuramedia.LinFileCopy.yml
│   └── debian/{control,rules,changelog,install}
└── docs/ CONCEPT.md  ARCHITECTURE.md  DEVELOPER.md  mockups/
```

The **pure-Python UI** is preferred over Glade. Glade is unmaintained for GTK 3, and
building the feature rows in code keeps each control next to the model field it edits.
If Glade files are needed later, only the static shell (`window.ui`) goes into Glade.

## 4. The job model

One `SyncJob` stores the whole configuration. Every group is a nested dataclass, so
a group maps cleanly to one UI section and one builder function.

```python
@dataclass
class SyncJob:
    id: str; name: str; description: str = ""
    source: Endpoint; destination: Endpoint          # B1, #20, #10
    mode: Mode = Mode.COPY                           # B2, #2, #13: COPY | MIRROR | TWO_WAY
    overwrite: OverwritePolicy = OverwritePolicy.ALWAYS   # B9
    preview_first: bool = True                       # B7, #4
    transfer: TransferOptions      # #1 delta/inplace, #7 resume, #8 checksum, #9 compress,
                                   # #6 bwlimit, #12 parallel, #15 sparse
    metadata: MetadataOptions      # B5, #3: perms, owner, group, times, acls, xattrs, hardlinks
    filters: FilterOptions         # B6, #5: presets, rules[], exclude_from, files_from
    safety: SafetyOptions          # #16 atomic, #17 snapshots(link_dest, keep_n)
    bisync: BisyncOptions          # #13 conflict policy, loser action, resync
    watch: WatchOptions            # #14 enabled, paths, debounce_s
    logging: LoggingOptions        # #18 level, notify_on {success,failure}, retries, backoff
    schedule: ScheduleOptions      # #19 kind, time, weekdays, cron expr, backend, enabled
    schema_version: int = 1
```

`Endpoint` = `{kind: LOCAL|SSH|RCLONE, path, host, user, port, key_file, remote_name, crypt_remote}`.
Secrets are **never** written to job JSON. SSH uses keys or the agent. rclone keeps its own
obscured config. Optional passwords go to libsecret under the job id.

`validation.py` returns structured issues, for example
`Issue(ERROR, "safety.atomic", "Atomic replace needs a local destination", fix="Switch destination to Local or disable atomic replace")`.
The designer shows these inline, and the Start button is disabled while any ERROR is present.

## 5. Build order (precedence)

The order follows three rules. (a) Nothing is built before the thing it depends on.
(b) The ten **basic features (B1–B10)** make a usable product first. (c) Advanced features
come afterwards, starting with the ones that are only flags and ending with the ones that
need their own strategies. Every phase ends with passing tests and a commit and push to
`origin/main`.

| Phase | Deliverable | Features | Exit criteria |
|---|---|---|---|
| **P0 Foundation** | package skeleton, `paths`, `i18n`, logging, icon vendoring + GResource, CSS, empty window with sidebar/stack, tool detection | — | app launches; all sidebar icons are embedded; `tools.py` reports rsync/rclone |
| **P1 Model** | `SyncJob` + enums, JSON (de)serialisation with schema version, validation, templates, JobStore | data for all 30 | round-trip tests; templates load |
| **P2 Command builders** | `rsync_builder`, `rclone_builder`, `planner`, command preview string (shell-quoted) | flags for B2 B5 B6 B7 B9 · #1–#10 #15 #17 #20 | golden tests: one per feature and one per incompatible combination |
| **P3 Runner + progress** | subprocess in its own process group, streaming parsers, pause (SIGSTOP/SIGCONT), cancel (SIGTERM→SIGKILL), exit-code mapping, retries | B3 B4 · #11 #18 | integration test runs a real local rsync between temp dirs |
| **P4 MVP UI** | Designer *Simple* view, Transfers page, dry-run preview dialog, History page with re-run, notifications, delete confirmation | **B1–B10 complete** | a basic job can be designed, previewed, run, paused, cancelled, found in history and re-run |
| **P5 Advanced designer** | *Advanced* view with one section per feature group, live command preview, copy to clipboard, drag and drop, templates menu | #1–#10 #12 #15 #20 in the UI | every control changes the preview; tooltips on every control |
| **P6 Strategies** | atomic replace, snapshots + rotation, parallel rsync, rclone bisync, inotify watcher | #12 #13 #14 #16 #17 | tests for each strategy on temp dirs; disabled states when tools are missing |
| **P7 Scheduling** | `cli.py run`, systemd user timer backend, crontab fallback, Scheduler page | #19 | a timer is created, listed, enabled/disabled and removed; the headless run records history |
| **P8 Polish** | tray (Ayatana), keyboard shortcuts, accessibility pass, dark mode, responsive breakpoints, gettext template | — | `ACCESSIBILITY` checklist passes; no main-loop stalls over 50 ms |
| **P9 Packaging** | `.desktop`, metainfo, app icon PNGs, Flatpak manifest, Debian control/rules, README, DEVELOPER.md | — | `pip install .` and `dpkg-buildpackage -b` both succeed |

### Why this order

- The builders (P2) come before any UI because the preview pane, the runner and the
  scheduler all use them. If they are wrong, every later phase is wrong.
- Progress and the runner (P3) come before the UI because pause and cancel shape the UI
  state machine (`Idle → Previewing → Ready → Running ⇄ Paused → Done/Failed/Cancelled`).
- Strategies (P6) come late because each one wraps the P3 runner in extra steps. They are
  multi-step `CommandPlan`s, not new runners.
- Scheduling (P7) needs a stable job store and a headless runner. Nothing else depends on it.

## 6. Feature → implementation map

### 6.1 Basic features (B1–B10) — built first, shown in the *Simple* view

| # | Feature | UI | rsync | rclone | Notes |
|---|---|---|---|---|---|
| B1 | Source & destination | two `PathField`s (drop target + Browse + type selector), swap button | positional args; trailing `/` handled explicitly by a "copy folder itself / contents" toggle | `src dst` | Drag and drop accepts `text/uri-list`. Source and destination are colour-coded (blue and green edge) |
| B2 | Copy vs Sync (mirror) | segmented buttons: **Copy · Mirror · Two-way** | Mirror → `--delete-delay` | `copy` vs `sync` | Mirror always confirms first with a count taken from a dry run |
| B3 | Progress, speed, ETA | progress card | `--info=progress2,name1,stats2 --outbuf=L` | `--use-json-log -v --stats 1s` | parsed into `ProgressSnapshot` at most 4 times per second |
| B4 | Start / Pause / Cancel | primary Start button + Pause/Cancel | SIGSTOP/SIGCONT/SIGTERM to the process group | same | pause shows a note that SSH can time out; ServerAliveInterval is set |
| B5 | Preserve dates & permissions | one checkbox, **on** by default | `-rlptD` (subset of `-a`) | `--metadata` is optional; times are kept by default | the Advanced view expands this to #3 |
| B6 | Skip common items | preset chips + custom list | `--exclude` rules | `--exclude`/`--filter` | presets: hidden files, caches (`.cache/`, `__pycache__/`, `node_modules/`), temp (`*.tmp`, `*~`, `.~lock*`), system (`lost+found/`, `.Trash-*/`) |
| B7 | Preview | **Preview** button + "Always preview first" switch | `--dry-run --itemize-changes` | `--dry-run` + JSON log | parsed into a list of create/update/delete rows with filters |
| B8 | Job history | History page; Re-run on each row | — | — | sqlite `runs` table: job snapshot, argv, exit code, bytes, files, duration, log path |
| B9 | Existing files | dropdown: Overwrite · Skip · Overwrite if newer | default · `--ignore-existing` · `--update` | default · `--ignore-existing` · `--update` | |
| B10 | Finish notification | switch (on) | — | — | `Gio.Notification` with a "Show" action. The tray badge is used when the window is hidden |

### 6.2 Top-20 features — the *Advanced* view

| # | Feature | UI | rsync | rclone | Constraints & validation |
|---|---|---|---|---|---|
| 1 | Delta transfer | switch "Delta (send changes only)" + `--inplace`, `--whole-file` in advanced options | default; `--inplace`; `-W` | n/a (whole-file by design) → info note | `--inplace` conflicts with #16 atomic and weakens #7; the validator warns |
| 2 | Incremental sync | default behaviour; "Compare by" dropdown: size+time / size only / checksum | default · `--size-only` · `-c` | default · `--size-only` · `--checksum` | shared with #8 |
| 3 | Metadata | checkbox group: permissions, owner, group, times, ACLs, xattrs, hard links, devices | `-p -o -g -t -A -X -H -D` | `--metadata` (+ `--links`) | owner/group need root at the destination → warning |
| 4 | Dry run | global **Preview** toggle in the header bar + Preview button | `-n -i` | `--dry-run` | the dry-run badge also appears on Transfers |
| 5 | Filters | rule list (include/exclude, pattern, ↑↓ order), Add/Remove, exclude-from and files-from file pickers, **Test** button | `--include`/`--exclude` in order, `--exclude-from`, `--files-from` | `--filter "+ …"/"- …"`, `--exclude-from`, `--files-from` | Test runs a dry run limited to listing and highlights matched paths |
| 6 | Bandwidth | switch + spin + unit (KB/s, MB/s) | `--bwlimit=<KiB>` | `--bwlimit <n>K/M` | 0 = unlimited |
| 7 | Resume | switch "Allow resume of interrupted files" | `--partial --partial-dir=.lfc-partial` | default (multi-part resume where the backend supports it) | partial dir is excluded from mirror deletes |
| 8 | Checksum | switch "Verify with checksums (slower)" | `-c` | `--checksum` | |
| 9 | Compression | switch + level 1–9 | `-z --compress-level=N` | n/a → note "use a compress remote" | disabled for local→local (pointless) with a tooltip saying why |
| 10 | Secure transport | protocol selector per endpoint: Local · SSH · rclone remote · rclone crypt; SSH: host, user, port, key file | `-e "ssh -p P -i K -o BatchMode=yes -o ServerAliveInterval=15"` | crypt remote picked from `rclone listremotes`; wizard wraps `rclone config create … crypt … --obscure` | Test connection button runs `ssh -o BatchMode=yes … true` |
| 11 | Progress & stats | Transfers page: bar, current file, speed sparkline, ETA, files done/total, bytes; stats pane after finish | `--stats` block parsed | JSON stats parsed | stats are stored in history |
| 12 | Parallel transfers | spin "Parallel streams" 1–16 | wrapper: split top-level entries into N balanced buckets → N rsync processes with `--files-from`; the progress bars are aggregated | `--transfers N --multi-thread-streams M` | rsync parallel is disabled with #16/#17 in v1 (single-pass semantics) |
| 13 | Bidirectional | mode **Two-way** + conflict policy: newer · older · larger · keep both (rename loser) · ask (stop and list) | n/a → requires rclone | `bisync --conflict-resolve … --conflict-loser … --resilient --recover` | first run needs `--resync`; the UI explains this and runs it with a preview |
| 14 | Real-time sync | switch "Run on change" + watch list (defaults to source) + debounce seconds | — | — | `inotify` via `ctypes` (recursive watches, 2 s debounce). Runs while the app or tray is alive. The scheduler can add a systemd `.path` unit for "watch even when closed" (non-recursive) |
| 15 | Sparse files | switch | `-S` | n/a (note) | allowed with `--inplace` on rsync ≥ 3.1.3 (validator checks the version) |
| 16 | Atomic replace | switch "Atomic replace (all-or-nothing)" | step 1: rsync into `<dest>.lfc-stage` with `--link-dest=<dest>`; step 2: `renameat2(RENAME_EXCHANGE)` via ctypes; step 3: remove old tree | n/a | local destination only; needs enough free space for changed files; conflicts with #1 inplace |
| 17 | Snapshots | switch + snapshot root + keep last N / daily / weekly | `dest/<YYYY-mm-ddTHHMMSS>` with `--link-dest=dest/latest`; update the `latest` symlink; rotate | n/a (`--backup-dir` alternative noted) | local or SSH destination |
| 18 | Logging & errors | log level dropdown, notify on failure/success, retries 0–10 + backoff | `--log-file` + captured stderr | `--log-file --log-level` | exit code → message + suggested fix (see `exitcodes.py`); retry only on transient codes (rsync 10, 12, 23, 24, 30, 35) |
| 19 | Scheduling | Scheduler page: Once · Hourly · Daily · Weekly · Custom (cron); backend auto (systemd → cron); enable switch | `linfilecopy run <id>` | same | systemd: `~/.config/systemd/user/linfilecopy-<id>.{service,timer}`; cron: managed block with `# linfilecopy:<id>` markers |
| 20 | Multi-backend | endpoint type selector: Local · SSH · Cloud (rclone remote) | local/SSH | any remote (S3, Drive, Dropbox, SFTP, …) | engine choice is automatic: any rclone endpoint → rclone, otherwise rsync. Shown as an "Engine: rsync" badge in the preview |

### 6.3 Progress parsing contracts

- **rsync** `--info=progress2`: `^\s*([\d,]+)\s+(\d+)%\s+(\S+/s)\s+(\d+:\d{2}:\d{2})(?:\s+\(xfr#(\d+), (?:ir|to)-chk=(\d+)/(\d+)\))?`.
  Lines with no `\r` and no percentage are file names (`name1`) and set `current_file`.
- **rsync** `-i` (preview): `^([<>ch.*][fdLDS][cstpoguax.+ ]{9})\s(.+)$` and `^\*deleting\s+(.+)$`.
- **rclone** JSON log: objects with `"stats"` → `bytes, totalBytes, speed, eta, transfers, totalTransfers, transferring[].name`.
- Parsers are pure functions over one line, and each has fixture tests.

### 6.4 Exit-code mapping (excerpt)

| rsync | Meaning shown | Suggested fix |
|---|---|---|
| 1 | Syntax or usage error | Report a bug. The generated command is in the log |
| 3 | Error selecting files | Check that the source path exists and is readable |
| 11 | File I/O error | Check free space on the destination and write permissions |
| 12 | Protocol stream error | Check the network or SSH connection; install rsync on the remote |
| 23 | Partial transfer (some files failed) | Open the log. Usually permission denied on some files |
| 24 | Source files vanished | Usually harmless; files changed during the copy |
| 30/35 | Timeout | Increase the timeout or check the connection |
| 255 (ssh) | SSH connection failed | Test the connection; check host, key and known_hosts |

## 7. Iconography

### 7.1 Embedding pipeline

1. `tools/icons.manifest` lists every icon the app uses: `lfc-name  phosphor-name  weight`.
2. `tools/vendor_icons.py` copies each file from the asset directory into
   `linfilecopy/data/icons/scalable/actions/lfc-<name>-symbolic.svg`, checks that
   `fill="currentColor"` is present, copies Phosphor's `LICENSE` and writes `ICONS.md`.
   The vendored SVGs are **committed**, so builds never need the asset directory.
3. `build_resources.sh` compiles the icons and CSS into `linfilecopy.gresource`.
4. At start-up, `resources.py` registers the bundle and calls
   `Gtk.IconTheme.get_default().add_resource_path("/io/github/mensuramedia/LinFileCopy/icons")`.
5. `ui/icons.py` exposes `icon("play", Gtk.IconSize.BUTTON)`. The `lfc-` prefix means no
   system theme icon can ever override one of ours. The `-symbolic` suffix lets GTK
   recolour it to the theme foreground, so the icons follow light and dark mode.

### 7.2 Weights and sizes

| Context | Size | Weight |
|---|---|---|
| Sidebar navigation | 20 px | regular; **fill** for the selected page |
| Buttons, header bar, rows | 16 px | regular |
| Primary action (Start) | 16 px | fill |
| Status badges | 16 px | fill (colour from the status class) |
| Stat tiles and empty states | 32 / 64 px | duotone rendered as a single colour (`-symbolic`) or light |

### 7.3 Icon map

**Navigation**

| Element | Icon | Why |
|---|---|---|
| Dashboard | `squares-four` | tiled overview |
| Job Designer | `sliders-horizontal` | configure options |
| Active Transfers | `pulse` | something is running now |
| History & Logs | `clock-counter-clockwise` | looking back |
| Scheduler | `calendar-check` | planned runs |
| Settings | `gear-six` | preferences |

**Job control**

| Action | Icon | | Action | Icon |
|---|---|---|---|---|
| Start / Resume | `play` (fill) | | Pause | `pause` |
| Cancel | `stop` | | Preview (dry run) | `eye` |
| Re-run | `arrow-clockwise` | | Retry failed | `arrow-counter-clockwise` |
| New job | `plus` | | Save job | `floppy-disk` |
| Duplicate | `copy-simple` | | Delete job | `trash` |
| Templates | `stack` | | Import / Export job | `arrow-square-in` / `arrow-square-out` |
| Copy command | `clipboard-text` | | Command preview pane | `terminal-window` |
| Browse folder | `folder-open` | | Drop zone hint | `hand-grabbing` |
| Swap source ↔ destination | `arrows-down-up` | | Test connection / filters | `flask` |
| Search | `magnifying-glass` | | Open log | `scroll` |
| Help / tooltip info | `info` | | Keyboard shortcuts | `keyboard` |
| Theme (system/light/dark) | `circle-half` | | Install instructions | `download-simple` |

**Endpoints (#10, #20)**

| Type | Icon | | Type | Icon |
|---|---|---|---|---|
| Local folder | `hard-drives` | | SSH | `terminal` |
| Cloud (generic rclone) | `cloud` | | Encrypted (crypt) | `lock-key` |
| SSH key file | `key` | | Password | `password` |
| Source side | `upload-simple` | | Destination side | `download-simple` |

**Modes and policies**

| Item | Icon | | Item | Icon |
|---|---|---|---|---|
| Copy (one-way) | `arrow-right` | | Mirror (sync) | `arrows-clockwise` |
| Two-way | `arrows-left-right` | | Conflict policy | `scales` |
| Overwrite | `swap` | | Skip existing | `skip-forward` |
| Overwrite if newer | `clock-clockwise` | | Delete warning | `warning` |

**Features (section headers in the Advanced view)**

| # | Feature | Icon | # | Feature | Icon |
|---|---|---|---|---|---|
| 1 | Delta | `git-diff` | 11 | Statistics | `chart-line-up` |
| 2 | Incremental / compare | `list-checks` | 12 | Parallel | `rows` |
| 3 | Metadata | `tag` | 13 | Bidirectional | `arrows-left-right` |
| 4 | Dry run | `eye` | 14 | Real-time | `lightning` |
| 5 | Filters | `funnel` | 15 | Sparse | `file-dashed` |
| 6 | Bandwidth | `gauge` | 16 | Atomic | `atom` |
| 7 | Resume | `play-pause` | 17 | Snapshots | `camera` (link-dest field: `link`) |
| 8 | Checksum | `fingerprint` | 18 | Logging | `scroll` (notify: `bell`, retries: `arrow-counter-clockwise`) |
| 9 | Compression | `file-zip` | 19 | Scheduling | `calendar-check` (cron: `clock`) |
| 10 | Security | `lock-key` | 20 | Backends | `plugs-connected` |

**Exclude presets (B6)**: hidden → `eye-slash` · caches → `broom` · temp → `hourglass` ·
system → `prohibit` · custom → `funnel-simple`.

**Status**: running → `circle-notch` (CSS spin) · paused → `pause-circle` · success →
`check-circle` · warnings → `warning-circle` · failed → `x-circle` · cancelled → `prohibit` ·
scheduled → `clock` · queued → `hourglass` · missing tool → `warning`.

**App icon**: a rounded-square tile with Phosphor `copy` over a `arrows-clockwise` badge,
built from the same local SVG paths (no external art). It is exported to PNG at
16/24/32/48/64/128/256/512 with `GdkPixbuf` during the build.

## 8. UI concept

- **Window**: `Gtk.HeaderBar` (app menu, global Preview toggle, New job) with a
  220 px sidebar (`Gtk.ListBox`) and a `Gtk.Stack`. Below 900 px the sidebar collapses
  to icons only, and below 640 px it becomes a popover opened from the header.
- **Designer**: a two-pane layout with the form on the left and a **sticky command preview**
  on the right. The panes stack vertically on narrow widths. A *Simple / Advanced* switch
  sits at the top. Simple shows B1–B10 only. Advanced adds collapsible sections with the
  icons listed above. Every control has a tooltip, a mnemonic label and an ATK label.
- **Source vs destination**: cards with a 4 px accent edge, blue for source and green for
  destination, with "FROM"/"TO" captions. The swap button sits between them.
- **Destructive actions**: Mirror mode shows a persistent `warning` info bar. Start opens a
  confirmation dialog with the delete count from an automatic dry run.
- **Theme**: follows `gtk-application-prefer-dark-theme` / the portal colour scheme.
  CSS uses `@define-color` tokens and has a dark variant.

### Keyboard shortcuts

| Keys | Action | | Keys | Action |
|---|---|---|---|---|
| Ctrl+N | New job | | Ctrl+S | Save job |
| Ctrl+Return | Start | | Ctrl+Shift+P | Preview |
| Space (Transfers) | Pause/Resume | | Escape (Transfers) | Cancel (asks first) |
| Ctrl+Shift+C | Copy command | | Ctrl+1…6 | Switch page |
| Ctrl+F | Search history | | Ctrl+? | Shortcuts window |

## 9. Persistence

| Data | Location | Format |
|---|---|---|
| Jobs | `$XDG_CONFIG_HOME/linfilecopy/jobs/<id>.json` | JSON, `schema_version` |
| Settings | `$XDG_CONFIG_HOME/linfilecopy/settings.json` | JSON |
| History | `$XDG_DATA_HOME/linfilecopy/history.db` | sqlite3 (stdlib) |
| Run logs | `$XDG_STATE_HOME/linfilecopy/logs/<run-id>.log` | text, rotated after 90 days |
| Secrets | libsecret (optional) | never in JSON |

## 10. Risks and decisions for review

1. **rclone is not installed** on the dev machine. Cloud, crypt and two-way features will be
   built against recorded output fixtures. Please install rclone if you want to verify them
   end to end.
2. **Two-way sync uses rclone bisync only** (unison is not planned for v1). Without rclone,
   Two-way is disabled and shows install instructions.
3. **Parallel rsync** is a wrapper that splits the work, not a native rsync feature. v1
   disables it together with atomic and snapshot modes.
4. **Real-time sync while closed** relies on systemd `.path` units, which are not recursive.
   Full recursive watching needs the app or tray to be running.
5. **Flatpak** needs `--talk-name=org.freedesktop.Flatpak` and `flatpak-spawn --host` for
   the scheduler (`systemctl --user`, `crontab`). rsync and rclone are bundled as modules in
   the manifest.
6. **Reference repositories** (`gtk-python-dashboard-starter`, `universal-instruction-set`)
   have not been reviewed yet. The fetch was stopped. The layout above is a proposal to
   reconcile with them before P0 starts.
