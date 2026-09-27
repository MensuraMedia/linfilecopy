"""Recursive folder watching with Linux inotify via ctypes (#14). No third-party packages.

:class:`FolderWatcher` watches one or more folder trees and calls
``on_change()`` (from its own thread) once changes have been quiet for
``debounce`` seconds. New sub-folders are watched as they appear.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
import select
import struct
import threading
import time
from typing import Callable

from linfilecopy.log import get_logger

_log = get_logger(__name__)
_libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)

IN_MODIFY = 0x002
IN_ATTRIB = 0x004
IN_CLOSE_WRITE = 0x008
IN_MOVED_FROM = 0x040
IN_MOVED_TO = 0x080
IN_CREATE = 0x100
IN_DELETE = 0x200
IN_DELETE_SELF = 0x400
IN_MOVE_SELF = 0x800
IN_Q_OVERFLOW = 0x4000
IN_IGNORED = 0x8000
IN_ISDIR = 0x40000000
IN_NONBLOCK = 0o4000
IN_CLOEXEC = 0o2000000
MASK = (IN_MODIFY | IN_ATTRIB | IN_CLOSE_WRITE | IN_MOVED_FROM | IN_MOVED_TO | IN_CREATE | IN_DELETE
        | IN_DELETE_SELF | IN_MOVE_SELF)
EVENT = struct.Struct("iIII")
MAX_WATCHES = 20000
IGNORED_NAMES = {".lfc-partial", ".lfc-trash", ".lfc-stage"}


class WatchError(Exception):
    pass


class FolderWatcher:
    def __init__(self, roots: list[str], on_change: Callable[[], None], debounce: float = 2.0) -> None:
        self.roots = [os.path.abspath(r) for r in roots]
        self.on_change = on_change
        self.debounce = max(0.2, debounce)
        self._fd = -1
        self._wd: dict[int, str] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_event = 0.0
        self._pending = False
        self.suppressed_until = 0.0   # events before this time are ignored (our own writes)

    # ----- lifecycle ----------------------------------------------------------------
    def start(self) -> None:
        self._fd = _libc.inotify_init1(IN_NONBLOCK | IN_CLOEXEC)
        if self._fd < 0:
            raise WatchError(os.strerror(ctypes.get_errno()))
        for root in self.roots:
            self._add_tree(root)
        self._thread = threading.Thread(target=self._loop, name="lfc-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    @property
    def watch_count(self) -> int:
        return len(self._wd)

    def suppress(self, seconds: float) -> None:
        self.suppressed_until = time.monotonic() + seconds
        self._pending = False

    # ----- watches ----------------------------------------------------------------------
    def _add(self, path: str) -> None:
        if len(self._wd) >= MAX_WATCHES:
            return
        wd = _libc.inotify_add_watch(self._fd, os.fsencode(path), MASK)
        if wd < 0:
            err = ctypes.get_errno()
            if err == errno.ENOSPC:
                _log.warning("inotify watch limit reached; not all folders under %s are watched", path)
            return
        self._wd[wd] = path

    def _add_tree(self, root: str) -> None:
        if not os.path.isdir(root):
            return
        for dirpath, dirnames, _files in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_NAMES]
            self._add(dirpath)
            if len(self._wd) >= MAX_WATCHES:
                _log.warning("watching the first %d folders only", MAX_WATCHES)
                return

    # ----- loop ------------------------------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            timeout = 0.5
            if self._pending:
                timeout = max(0.05, self._last_event + self.debounce - time.monotonic())
            try:
                ready, _w, _x = select.select([self._fd], [], [], timeout)
            except (OSError, ValueError):
                return
            if ready:
                self._read()
            if self._pending and time.monotonic() - self._last_event >= self.debounce:
                self._pending = False
                try:
                    self.on_change()
                except Exception:  # noqa: BLE001 - never kill the watcher thread
                    _log.exception("change callback failed")

    def _read(self) -> None:
        try:
            data = os.read(self._fd, 64 * 1024)
        except BlockingIOError:
            return
        except OSError:
            return
        offset = 0
        interesting = False
        while offset + EVENT.size <= len(data):
            wd, mask, _cookie, length = EVENT.unpack_from(data, offset)
            name = data[offset + EVENT.size: offset + EVENT.size + length].rstrip(b"\0").decode("utf-8", "replace")
            offset += EVENT.size + length
            if mask & IN_Q_OVERFLOW:
                interesting = True
                continue
            if mask & IN_IGNORED:
                self._wd.pop(wd, None)
                continue
            base = self._wd.get(wd)
            if base is None or name in IGNORED_NAMES or any(part in IGNORED_NAMES for part in base.split(os.sep)):
                continue
            if mask & IN_ISDIR and mask & (IN_CREATE | IN_MOVED_TO):
                self._add_tree(os.path.join(base, name))
            interesting = True
        if interesting and time.monotonic() >= self.suppressed_until:
            self._last_event = time.monotonic()
            self._pending = True
