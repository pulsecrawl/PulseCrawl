"""Confined staging and atomic publication of untrusted artifact paths."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import ctypes
import errno
import os
from pathlib import Path
import stat
import uuid

from .publication import publish_file


_UNSAFE_PARENT = (
    "dataset artifact path escapes destination through a symlink or non-directory"
)


@contextmanager
def _windows_directory(path: Path):
    """Pin a real directory against rename/delete while descendants are used.

    Windows has no Python dir_fd operations. Denying write/delete sharing
    blocks both reparse-point mutation and rename/delete of pinned parents.
    Existing reparse points are never followed.
    """
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    info = kernel.GetFileInformationByHandleEx
    info.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    info.restype = wintypes.BOOL

    class Attributes(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

    # GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING,
    # BACKUP_SEMANTICS | OPEN_REPARSE_POINT. Child creation does not require
    # opening the parent itself for write access.
    # Attribute-only access does not participate in Windows sharing checks.
    handle = create(str(path), 0x80000000, 1, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        attributes = Attributes()
        if not info(handle, 9, ctypes.byref(attributes), ctypes.sizeof(attributes)):
            raise ctypes.WinError(ctypes.get_last_error())
        if attributes.attributes & 0x400 or not attributes.attributes & 0x10:
            raise ValueError(_UNSAFE_PARENT)
        yield
    finally:
        close(handle)


@contextmanager
def stage_artifact(root: Path, parts: tuple[str, ...], *, overwrite: bool):
    """Yield a binary staging stream and publish only after successful completion.

    Every parent is validated and pinned before creating its child. Cleanup
    only removes this operation's private temporary file, never a target.
    """
    with ExitStack() as stack:
        parent_fd = None
        parent = root
        if os.name == "nt":
            stack.enter_context(_windows_directory(parent))
            for part in parts[:-1]:
                parent = parent / part
                parent.mkdir(exist_ok=True)
                stack.enter_context(_windows_directory(parent))
        else:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

            def pin(name, directory_fd=None):
                try:
                    descriptor = os.open(name, flags, dir_fd=directory_fd)
                except OSError as exc:
                    if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                        raise ValueError(_UNSAFE_PARENT) from exc
                    raise
                stack.callback(os.close, descriptor)
                return descriptor

            parent_fd = pin(root)
            for part in parts[:-1]:
                try:
                    os.mkdir(part, dir_fd=parent_fd)
                except FileExistsError:
                    pass
                parent_fd = pin(part, parent_fd)

        name = parts[-1]
        target = parent / name if parent_fd is None else name
        options = {} if parent_fd is None else {"dir_fd": parent_fd}
        try:
            existing = os.stat(target, follow_symlinks=False, **options)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not overwrite:
                raise FileExistsError(f"refusing to overwrite {root.joinpath(*parts)}")
            if not stat.S_ISREG(existing.st_mode):
                raise ValueError("dataset artifact target is not a regular file")

        token = f".pulsecrawl-download-{uuid.uuid4().hex}.tmp"
        temporary = parent / token if parent_fd is None else token
        descriptor = os.open(
            temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, **options
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                yield handle
                handle.flush()
                os.fsync(handle.fileno())
            publish_file(temporary, target, overwrite=overwrite, directory_fd=parent_fd)
        finally:
            try:
                os.unlink(temporary, **options)
            except FileNotFoundError:
                pass
