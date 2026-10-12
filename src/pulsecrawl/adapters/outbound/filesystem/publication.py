"""Atomic, no-clobber publication of complete workspace directories."""

from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
import sys


def publish_directory(source: Path, destination: Path) -> None:
    """Rename a sibling directory without replacing *any* existing target.

    An exists-then-rename check is not sufficient: POSIX rename can overwrite
    an empty directory created by another process between those operations.
    Unsupported platforms/filesystems fail closed, never fall back to replace.
    """
    _rename_no_replace(source, destination)


def publish_file(
    source: str | Path,
    destination: str | Path,
    *,
    overwrite: bool = False,
    directory_fd: int | None = None,
) -> None:
    """Publish a staged file, with an atomic no-clobber default."""
    if overwrite:
        if directory_fd is None:
            os.replace(source, destination)
        else:
            os.replace(
                source, destination, src_dir_fd=directory_fd, dst_dir_fd=directory_fd
            )
    else:
        _rename_no_replace(source, destination, directory_fd=directory_fd)


def _rename_no_replace(
    source: str | Path, destination: str | Path, *, directory_fd: int | None = None
) -> None:
    if sys.platform == "win32":
        # Unlike POSIX rename, Windows rename refuses an existing destination.
        os.rename(source, destination)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = getattr(
            libc, "renamex_np" if directory_fd is None else "renameatx_np", None
        )
        if rename is None:
            raise OSError(errno.ENOTSUP, "exclusive directory rename unavailable")
        rename.restype = ctypes.c_int
        if directory_fd is None:
            rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
            result = rename(os.fsencode(source), os.fsencode(destination), 0x00000004)
        else:
            rename.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            result = rename(
                directory_fd,
                os.fsencode(source),
                directory_fd,
                os.fsencode(destination),
                0x00000004,
            )
    elif sys.platform.startswith("linux"):
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise OSError(errno.ENOTSUP, "exclusive directory rename unavailable")
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        # AT_FDCWD, RENAME_NOREPLACE; both paths are siblings on one filesystem.
        parent_fd = -100 if directory_fd is None else directory_fd
        result = rename(
            parent_fd, os.fsencode(source), parent_fd, os.fsencode(destination), 1
        )
    else:
        raise OSError(errno.ENOTSUP, "exclusive directory rename unavailable")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))
