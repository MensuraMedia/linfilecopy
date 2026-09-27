"""rsync exit codes -> status, plain-language message and suggested fix (#18, CONCEPT §6.6)."""
from __future__ import annotations

from dataclasses import dataclass

from linfilecopy.i18n import _
from linfilecopy.model.enums import RunStatus


@dataclass(frozen=True)
class ExitInfo:
    code: int
    status: RunStatus
    message: str
    fix: str
    transient: bool = False    # worth retrying automatically


def _table() -> dict[int, ExitInfo]:
    F, W, S = RunStatus.FAILED, RunStatus.WARNING, RunStatus.SUCCESS
    rows = [
        (0, S, _("Completed"), "", False),
        (1, F, _("rsync reported a usage error."), _("This is a bug in LinFileCopy. Copy the command from the log and report it."), False),
        (2, F, _("rsync and the destination do not agree on the protocol."), _("Update rsync."), False),
        (3, F, _("Some files or folders could not be selected."), _("Check that the source folder exists and that you can read it."), False),
        (4, F, _("This rsync does not support an option the job uses."), _("Update rsync, or turn off the newest options (sparse, ACLs)."), False),
        (5, F, _("rsync could not start."), _("Check that rsync is installed correctly."), False),
        (6, F, _("rsync could not write its log."), _("Check free space in your home folder."), False),
        (10, F, _("Socket error."), _("Try again."), True),
        (11, F, _("Reading or writing a file failed."), _("The drive may be full, read-only or disconnected. Check free space and reconnect it."), True),
        (12, F, _("The data stream broke off."), _("Usually a drive that was removed during the copy. Reconnect it and run again; resume picks up partial files."), True),
        (13, F, _("rsync failed to write its diagnostics."), _("Try again."), False),
        (14, F, _("rsync could not start a helper process."), _("Close other programs and try again."), True),
        (20, RunStatus.CANCELLED, _("The run was stopped."), _("You cancelled it, or the system was shutting down."), False),
        (21, F, _("A helper process failed."), _("Try again."), True),
        (22, F, _("Out of memory."), _("Close other programs, or split the job into smaller folders."), False),
        (23, F, _("Some files could not be copied."), _("Open the log. Usually permission denied, or names or sizes the destination filesystem cannot store."), True),
        (24, W, _("Some source files disappeared during the copy."), _("Usually harmless: the files changed while copying."), False),
        (25, F, _("The deletion limit was reached."), _("Check the job; it stopped to avoid deleting too much."), False),
        (30, F, _("Timed out waiting for data."), _("The drive may be very slow or stuck. Reconnect it and try again."), True),
        (35, F, _("Timed out waiting for a connection."), _("Try again."), True),
        (127, F, _("rsync was not found."), _("Install rsync, for example: sudo apt install rsync"), False),
    ]
    return {c: ExitInfo(c, s, m, f, t) for c, s, m, f, t in rows}


_TABLE: dict[int, ExitInfo] | None = None


def explain(code: int) -> ExitInfo:
    global _TABLE
    if _TABLE is None:
        _TABLE = _table()
    if code in _TABLE:
        return _TABLE[code]
    if code < 0:
        return ExitInfo(code, RunStatus.CANCELLED, _("rsync was stopped by a signal."), _("Run the job again."), False)
    return ExitInfo(code, RunStatus.FAILED, _("rsync failed with code {code}.").format(code=code), _("Open the log for details."), False)


def refine_with_stderr(info: ExitInfo, stderr_lines: list[str]) -> ExitInfo:
    """Make the fix specific when stderr shows a known cause."""
    text = "\n".join(stderr_lines[-50:]).lower()
    if "no space left on device" in text:
        return ExitInfo(info.code, info.status, _("The destination drive is full."),
                        _("Free up space on the destination or choose a bigger drive."), False)
    if "file too large" in text:
        return ExitInfo(info.code, info.status, _("Some files are too large for the destination filesystem."),
                        _("FAT32 drives cannot hold files over 4 GB. Use an exFAT or ext4 drive."), False)
    if "read-only file system" in text:
        return ExitInfo(info.code, info.status, _("The destination is read-only."),
                        _("Remount the drive read-write, or check it for errors."), False)
    if "permission denied" in text and info.code == 23:
        return ExitInfo(info.code, info.status, info.message,
                        _("Some files could not be read or written: permission denied. Give your user access, or exclude those folders."),
                        False)
    if ("input/output error" in text or "no such device" in text) and info.code in (11, 12, 23):
        return ExitInfo(info.code, info.status, _("The drive stopped responding or was removed."),
                        _("Reconnect the drive and run the job again."), True)
    return info
