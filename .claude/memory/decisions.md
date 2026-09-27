# Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-09-27 | GTK 3 + PyGObject, pure-Python UI (no Glade) | Spec mandates GTK3; Glade unmaintained; starter repo is pure Python |
| 2026-09-27 | No external runtime deps; icons vendored from local Phosphor set into GResource | User's mandatory build philosophy |
| 2026-09-27 | Local storage only; rsync is the sole engine | User: no cloud supported in environment |
| 2026-09-27 | #9 compression dropped | rsync does not compress local copies (user approved) |
| 2026-09-27 | #13 two-way sync implemented natively (sqlite state, .lfc-trash, delete guard) | No unison/rclone; user approved |
| 2026-09-27 | #10 = LUKS unlock/lock via UDisks2; #20 = drive-aware endpoints (UUID, fs capabilities, eject) | Local reinterpretation of network features |
| 2026-09-27 | Structure follows gtk-python-dashboard-starter (BasePage/build_content, NavigationManager, role-prefixed modules) but uses Gtk.Application + HeaderBar and package-relative imports | Starter is a plain Gtk.Window with src/-relative imports; Gtk.Application needed for notifications, single instance, actions |
| 2026-09-27 | Adwaita-like light/dark following system, dark palette slate-toned per -universal-themes references, user-selectable accent (starter's accent themes) | Combines spec, theme references and starter |
| 2026-09-27 | Universal permissions (dontAsk/allow-all) NOT auto-deployed by Claude | Widens Claude's own permissions; left for the user to apply |
| 2026-09-27 | App ID io.github.mensuramedia.LinFileCopy | Reverse-DNS of GitHub org |
| 2026-09-28 | Page scrollers allow horizontal scrolling as a fallback | Lets GTK shrink the window past the current layout's minimum so responsive layout switches can trigger |
| 2026-09-28 | Keep all snapshots from the last 24 h in rotation | Running twice a day must not delete the earlier snapshot |
| 2026-09-28 | Two-way apply uses rsync --files-from --ignore-times | Decisions are already made; rsync's whole-second quick check could otherwise skip a decided copy |
| 2026-09-28 | App icon composed at build time from vendored Phosphor glyphs (copy + arrows-clockwise, bold) | "All iconography from the local source" applies to the app icon too |
