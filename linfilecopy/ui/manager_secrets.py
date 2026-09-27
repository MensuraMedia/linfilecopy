"""Drive passphrases: optional keyring storage (libsecret) and the prompt dialog (#10).

Passphrases never touch job files, logs or history. They are stored in the
system keyring only when the user ticks "Remember"."""
from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from linfilecopy.engine.drives import DriveInfo  # noqa: E402
from linfilecopy.i18n import _  # noqa: E402
from linfilecopy.log import get_logger  # noqa: E402
from linfilecopy.ui.components.component_common import esc, label  # noqa: E402
from linfilecopy.ui.icons import icon, SIZE_TILE  # noqa: E402

_log = get_logger(__name__)
_SCHEMA = None


def _secret():  # type: ignore[no-untyped-def]
    global _SCHEMA
    try:
        gi.require_version("Secret", "1")
        from gi.repository import Secret
    except (ImportError, ValueError):
        return None, None
    if _SCHEMA is None:
        _SCHEMA = Secret.Schema.new("io.github.mensuramedia.LinFileCopy.Drive", Secret.SchemaFlags.NONE,
                                    {"luks-uuid": Secret.SchemaAttributeType.STRING})
    return Secret, _SCHEMA


def keyring_available() -> bool:
    return _secret()[0] is not None


def lookup(luks_uuid: str) -> str | None:
    """Blocking keyring lookup; call from a worker thread."""
    Secret, schema = _secret()
    if Secret is None:
        return None
    try:
        return Secret.password_lookup_sync(schema, {"luks-uuid": luks_uuid}, None)
    except GLib.Error as exc:
        _log.warning("keyring lookup failed: %s", exc.message)
        return None


def store(luks_uuid: str, label_text: str, passphrase: str) -> None:
    Secret, schema = _secret()
    if Secret is None:
        return
    try:
        Secret.password_store_sync(schema, {"luks-uuid": luks_uuid}, Secret.COLLECTION_DEFAULT,
                                   _("LinFileCopy: passphrase for {drive}").format(drive=label_text), passphrase, None)
    except GLib.Error as exc:
        _log.warning("keyring store failed: %s", exc.message)


def forget(luks_uuid: str) -> None:
    Secret, schema = _secret()
    if Secret is not None:
        try:
            Secret.password_clear_sync(schema, {"luks-uuid": luks_uuid}, None)
        except GLib.Error:
            pass


class PassphraseDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window | None, drive: DriveInfo, job_name: str | None = None) -> None:
        super().__init__(title=_("Unlock {drive}").format(drive=drive.label), transient_for=parent, modal=True)
        self.set_default_size(420, -1)
        self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        ok = self.add_button(_("Unlock"), Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        self.set_default_response(Gtk.ResponseType.OK)
        box = self.get_content_area()
        box.set_spacing(12)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(18)
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        head.pack_start(icon("ep-encrypted", SIZE_TILE), False, False, 0)
        why = (_("<b>{job}</b> needs {drive} unlocked.").format(job=esc(job_name), drive=esc(drive.label))
               if job_name else _("Enter the passphrase for {drive}.").format(drive=esc(drive.label)))
        head.pack_start(label(why, markup=True, wrap=True), True, True, 0)
        box.pack_start(head, False, False, 0)
        self.entry = Gtk.Entry(visibility=False, activates_default=True, input_purpose=Gtk.InputPurpose.PASSWORD)
        self.entry.set_placeholder_text(_("Passphrase"))
        self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "lfc-ep-password-symbolic")
        self.entry.get_accessible().set_name(_("Passphrase"))
        box.pack_start(self.entry, False, False, 0)
        self.remember = Gtk.CheckButton(label=_("Remember in the keyring (needed for scheduled runs)"))
        self.remember.set_sensitive(keyring_available())
        box.pack_start(self.remember, False, False, 0)
        self.show_all()

    def ask(self) -> tuple[str | None, bool]:
        response = self.run()
        text = self.entry.get_text() if response == Gtk.ResponseType.OK else None
        remember = self.remember.get_active()
        self.entry.set_text("")
        self.destroy()
        return (text or None), remember


def request_from_worker(parent_getter, drive: DriveInfo, job_name: str) -> str | None:  # type: ignore[no-untyped-def]
    """Called on a run's worker thread: keyring first, then a dialog on the main thread."""
    stored = lookup(drive.uuid)
    if stored:
        return stored
    result: dict[str, str | None] = {"value": None}
    done = threading.Event()

    def ask() -> bool:
        dlg = PassphraseDialog(parent_getter(), drive, job_name)
        value, remember = dlg.ask()
        if value and remember:
            store(drive.uuid, drive.label, value)
        result["value"] = value
        done.set()
        return GLib.SOURCE_REMOVE

    GLib.idle_add(ask)
    done.wait()
    return result["value"]
