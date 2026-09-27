"""Atomic directory replacement (#16).

The destination is cloned with hard links into a staging folder (no extra
space), rsync updates the stage (it writes changed files as new inodes, so the
live copy is untouched), then the stage and the live folder are exchanged in
one ``renameat2(RENAME_EXCHANGE)`` call. Readers see either the old or the
new tree, never a half-updated one.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
import shutil
from typing import Callable

AT_FDCWD = -100
RENAME_EXCHANGE = 1 << 1

_libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)


def rename_exchange(a: str, b: str) -> None:
    """Swap two paths atomically. Raises OSError (ENOSYS/EINVAL when unsupported)."""
    func = getattr(_libc, "renameat2", None)
    if func is None:
        raise OSError(errno.ENOSYS, "renameat2 not available")
    func.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    if func(AT_FDCWD, os.fsencode(a), AT_FDCWD, os.fsencode(b), RENAME_EXCHANGE) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), a)


def hardlink_clone(source: str, target: str, check: Callable[[], None] | None = None) -> int:
    """Recreate ``source`` at ``target`` with hard links. Returns the number of files linked."""
    if os.path.lexists(target):
        remove_tree(target)   # leftover from an interrupted run
    count = 0
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        rel = os.path.relpath(dirpath, source)
        tdir = target if rel == "." else os.path.join(target, rel)
        os.makedirs(tdir, exist_ok=True)
        shutil.copystat(dirpath, tdir, follow_symlinks=False)
        for name in dirnames[:]:
            src = os.path.join(dirpath, name)
            if os.path.islink(src):          # symlinked dirs are links, not walked
                os.symlink(os.readlink(src), os.path.join(tdir, name))
                dirnames.remove(name)
        for name in filenames:
            src = os.path.join(dirpath, name)
            dst = os.path.join(tdir, name)
            if os.path.islink(src):
                os.symlink(os.readlink(src), dst)
            else:
                os.link(src, dst)
                count += 1
        if check is not None:
            check()
    return count


def swap_into_place(stage: str, target: str, target_exists: bool) -> None:
    """Make ``stage`` live at ``target``; afterwards ``stage`` holds the previous tree."""
    stage, target = stage.rstrip("/"), target.rstrip("/")
    if not target_exists or not os.path.lexists(target):
        os.rename(stage, target)
        return
    try:
        rename_exchange(stage, target)
    except OSError as exc:
        if exc.errno not in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
            raise
        # Filesystem without exchange support: two quick renames.
        old = target + ".lfc-old"
        os.rename(target, old)
        try:
            os.rename(stage, target)
        except OSError:
            os.rename(old, target)   # put the live tree back
            raise
        os.rename(old, stage)


def remove_tree(path: str) -> None:
    if not os.path.lexists(path):
        return

    def onerror(func, p, _exc):  # type: ignore[no-untyped-def]
        try:
            os.chmod(os.path.dirname(p), 0o700)
            if not os.path.islink(p):
                os.chmod(p, 0o700)
        except OSError:
            pass
        func(p)

    if os.path.islink(path) or not os.path.isdir(path):
        os.unlink(path)
    else:
        shutil.rmtree(path, onerror=onerror)
