"""Main window: header bar, sidebar navigation and the page stack."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from linfilecopy import APP_NAME  # noqa: E402
from linfilecopy.i18n import _  # noqa: E402
from linfilecopy.ui.components.component_common import label  # noqa: E402
from linfilecopy.ui.context import AppContext  # noqa: E402
from linfilecopy.ui.icons import button, icon  # noqa: E402
from linfilecopy.ui.manager_navigation import NavigationManager  # noqa: E402
from linfilecopy.ui.pages.page_base import BasePage  # noqa: E402
from linfilecopy.ui.sidebar import NAV_ITEMS, Sidebar  # noqa: E402

COMPACT_WIDTH = 900  # below: sidebar shows icons only
NARROW_WIDTH = 640   # below: sidebar hidden behind a header button


class MainWindow(Gtk.ApplicationWindow):
    """The single application window."""

    def __init__(self, app: Gtk.Application, ctx: AppContext, pages: list[BasePage]) -> None:
        super().__init__(application=app)
        self.ctx = ctx
        self.set_default_size(1180, 780)
        self.set_size_request(360, 480)
        self.nav = NavigationManager()
        self._narrow = False
        self._layout_mode = ""
        self._build_header()

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.sidebar = Sidebar()
        self.sidebar.connect("page-changed", lambda _s, pid: self.show_page(pid))
        body.pack_start(self.sidebar, False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)
        self.nav.set_stack(self.stack)
        for page in pages:
            self.stack.add_named(page, page.page_id)
            self.nav.register_page(page.page_id, page)
        body.pack_start(self.stack, True, True, 0)
        self.add(body)

        self._build_templates_menu()
        ctx.subscribe("drives", self._fill_sidebar_drives)
        ctx.subscribe("settings-changed", lambda _s: self._fill_sidebar_drives(ctx.drives.drives if ctx.drives else []))
        if ctx.drives is not None:
            self._fill_sidebar_drives(ctx.drives.drives)
        self.nav.on_navigate(self._on_navigated)
        self.connect("size-allocate", self._on_size_allocate)
        self.show_all()
        for page in pages:
            page.after_show_all()
        self.show_page("dashboard")

    # ----- header ---------------------------------------------------------
    def _build_header(self) -> None:
        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title_box.set_valign(Gtk.Align.CENTER)
        self.title_label = label(APP_NAME, xalign=0.5)
        self.title_label.get_style_context().add_class("title")
        self.subtitle_label = label("", "subtitle", xalign=0.5)
        for lbl in (self.title_label, self.subtitle_label):
            lbl.set_ellipsize(3)          # Pango.EllipsizeMode.END: long job names never widen the window
            lbl.set_max_width_chars(28)
        title_box.pack_start(self.title_label, False, False, 0)
        title_box.pack_start(self.subtitle_label, False, False, 0)
        hb.set_custom_title(title_box)

        self.sidebar_toggle = Gtk.ToggleButton()
        self.sidebar_toggle.add(icon("sidebar-toggle"))
        self.sidebar_toggle.set_tooltip_text(_("Show pages"))
        self.sidebar_toggle.get_accessible().set_name(_("Show pages"))
        self.sidebar_toggle.connect("toggled", lambda b: self.sidebar.set_visible(b.get_active()))
        self.sidebar_toggle.get_child().show()   # the button itself is excluded from show_all()
        self.sidebar_toggle.set_no_show_all(True)
        hb.pack_start(self.sidebar_toggle)

        new_btn = button("action-new", _("New job"), _("Create a new job (Ctrl+N)"))
        new_btn.set_action_name("app.new-job")
        hb.pack_start(new_btn)

        self.templates_button = Gtk.MenuButton()
        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        tb.pack_start(icon("action-templates"), False, False, 0)
        tb.pack_start(Gtk.Label(label=_("Templates")), False, False, 0)
        tb.pack_start(icon("action-collapse", 12), False, False, 0)
        self.templates_button.add(tb)
        self.templates_button.set_relief(Gtk.ReliefStyle.NONE)
        self.templates_button.set_tooltip_text(_("Start a new job from a template"))
        hb.pack_start(self.templates_button)

        menu = Gio.Menu()
        section = Gio.Menu()
        section.append(_("Keyboard Shortcuts"), "app.shortcuts")
        section.append(_("About LinFileCopy"), "app.about")
        menu.append_section(None, section)
        quit_section = Gio.Menu()
        quit_section.append(_("Quit"), "app.quit")
        menu.append_section(None, quit_section)
        menu_btn = Gtk.MenuButton()
        menu_btn.add(icon("app-menu"))
        menu_btn.set_menu_model(menu)
        menu_btn.set_tooltip_text(_("Main menu"))
        menu_btn.get_accessible().set_name(_("Main menu"))
        hb.pack_end(menu_btn)

        self.preview_toggle = Gtk.ToggleButton()
        pb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pb.pack_start(icon("action-preview"), False, False, 0)
        self.preview_toggle_label = Gtk.Label(label=_("Preview mode"))
        pb.pack_start(self.preview_toggle_label, False, False, 0)
        self.preview_toggle.add(pb)
        self.preview_toggle.set_action_name("app.preview-mode")
        self.preview_toggle.set_tooltip_text(
            _("When on, Start only shows what would change. Nothing is copied or deleted.")
        )
        hb.pack_end(self.preview_toggle)
        self.set_titlebar(hb)
        self.header = hb

    def _build_templates_menu(self) -> None:
        from linfilecopy.model.templates import load_templates

        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(6)
        for tpl in load_templates():
            b = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.pack_start(icon(tpl.icon), False, False, 0)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            text.pack_start(label(_(tpl.name)), False, False, 0)
            desc = label(_(tpl.description), "lfc-dim", "lfc-small", wrap=True)
            desc.set_max_width_chars(42)
            text.pack_start(desc, False, False, 0)
            row.pack_start(text, True, True, 0)
            b.add(row)
            b.connect("clicked", lambda _b, key=tpl.key: (pop.popdown(), self.ctx.publish("new-from-template", key)))
            box.pack_start(b, False, False, 0)
        box.show_all()
        pop.add(box)
        self.templates_button.set_popover(pop)

    def _fill_sidebar_drives(self, drives: list) -> None:  # type: ignore[type-arg]
        from linfilecopy.engine.drives import visible_drives
        from linfilecopy.model.enums import DriveKind
        from linfilecopy.ui.components.component_common import clear
        from linfilecopy.ui.components.component_path_card import drive_icon

        clear(self.sidebar.drives_list)
        shown = [d for d in visible_drives(drives, self.ctx.settings.show_system_partitions)
                 if d.kind is not DriveKind.INTERNAL or d.mount_point not in ("/",)]
        for d in shown:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.get_style_context().add_class("lfc-drive-row")
            img = icon(drive_icon(d))
            img.get_style_context().add_class("lfc-dim")
            row.pack_start(img, False, False, 0)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            name = label(d.label, ellipsize=True)
            name.set_max_width_chars(14)
            text.pack_start(name, False, False, 0)
            from linfilecopy.formatting import format_bytes

            detail = (_("locked") if d.encrypted and d.locked else
                      f"{d.fs.label} · {format_bytes(d.free)} " + _("free") if d.free is not None else d.fs.label)
            text.pack_start(label(detail, "lfc-dim", "lfc-small", ellipsize=True), False, False, 0)
            row.pack_start(text, True, True, 0)
            if d.kind is DriveKind.REMOVABLE and (d.mounted or d.can_power_off):
                b = button("action-eject", None, _("Eject {drive}").format(drive=d.label), flat=True)
                b.connect("clicked", lambda _b, d=d: self.ctx.drives.eject(d))
                row.pack_start(b, False, False, 0)
            elif d.encrypted and d.locked:
                b = button("ep-unlock", None, _("Unlock {drive}").format(drive=d.label), flat=True)
                b.connect("clicked", lambda _b, d=d: self.page("settings")._unlock(d))
                row.pack_start(b, False, False, 0)
            row.set_tooltip_text(f"{d.label}\n{d.describe()}\n{d.mount_point or d.device}")
            self.sidebar.drives_list.pack_start(row, False, False, 0)
        self.sidebar.drives_box.set_visible(bool(shown) and not self.sidebar._compact)
        self.sidebar.drives_list.show_all()

    # ----- navigation -----------------------------------------------------
    def show_page(self, page_id: str) -> None:
        self.nav.navigate_to(page_id)
        self.sidebar.select(page_id)
        if self._narrow:
            self.sidebar_toggle.set_active(False)

    def show_page_index(self, index: int) -> None:
        if 0 <= index < len(NAV_ITEMS):
            self.show_page(NAV_ITEMS[index][0])

    def page(self, page_id: str) -> BasePage:
        return self.nav.pages[page_id]  # type: ignore[return-value]

    def refresh_subtitle(self) -> None:
        page = self.nav.pages.get(self.nav.current or "")
        if isinstance(page, BasePage):
            self.subtitle_label.set_text(page.subtitle())

    def _on_navigated(self, page_id: str) -> None:
        if page_id != "designer":
            self.title_label.set_text(APP_NAME)
        self.refresh_subtitle()

    # ----- responsive layout ----------------------------------------------
    def _on_size_allocate(self, _w: Gtk.Widget, _alloc: object) -> None:
        width = self.get_allocated_width()
        mode = "narrow" if width < NARROW_WIDTH else "compact" if width < COMPACT_WIDTH else "wide"
        if mode != self._layout_mode:
            self._layout_mode = mode
            # Changing visibility during allocation is not allowed; defer it.
            GLib.idle_add(self._apply_layout_mode, mode)

    def _apply_layout_mode(self, mode: str) -> bool:
        narrow = mode == "narrow"
        self.sidebar.set_compact(mode == "compact")
        self.preview_toggle_label.set_visible(mode == "wide")
        self.templates_button.set_visible(not narrow)
        self._narrow = narrow
        self.sidebar_toggle.set_visible(narrow)
        self.sidebar_toggle.set_active(False)
        self.sidebar.set_visible(not narrow)
        return GLib.SOURCE_REMOVE
