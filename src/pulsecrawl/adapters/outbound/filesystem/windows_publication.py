"""Same-directory Windows rename without reopening a pinned parent for write."""

from __future__ import annotations

import ctypes
from pathlib import Path


def publish_pinned_file(source: Path, name: str, *, overwrite: bool) -> None:
    """Atomically rename an owned staging file within its existing parent.

    MoveFileEx (used by os.rename/replace) reopens the destination directory for
    write, conflicting with the write-sharing exclusion that prevents reparse
    mutation. Native FileRenameInformation with a bare filename stays in the
    source handle's parent. Never release the parent lock to make rename work.
    https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information
    """
    from ctypes import wintypes

    if not name or name in {".", ".."} or Path(name).name != name or any(c in name for c in "/\\:\0"):
        raise ValueError("pinned publication requires a single filename")

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    native = ctypes.WinDLL("ntdll")
    rename = native.NtSetInformationFile
    rename.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                       wintypes.ULONG, ctypes.c_int]
    rename.restype = ctypes.c_int32
    error_code = native.RtlNtStatusToDosError
    error_code.argtypes = [ctypes.c_int32]
    error_code.restype = wintypes.ULONG

    class RenameInfo(ctypes.Structure):
        _fields_ = [("replace", wintypes.BOOLEAN), ("root", wintypes.HANDLE),
                    ("length", wintypes.ULONG), ("name", wintypes.WCHAR * 1)]

    class IoStatus(ctypes.Structure):
        # The first field is an NTSTATUS/pointer union, hence pointer-sized.
        _fields_ = [("status", ctypes.c_void_p), ("information", ctypes.c_size_t)]

    encoded = name.encode("utf-16-le")
    size = max(ctypes.sizeof(RenameInfo), RenameInfo.name.offset + len(encoded) + 2)
    buffer = ctypes.create_string_buffer(size)
    info = RenameInfo.from_buffer(buffer)
    info.replace, info.root, info.length = overwrite, None, len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + RenameInfo.name.offset, encoded, len(encoded))
    # DELETE | FILE_READ_ATTRIBUTES, all sharing, OPEN_EXISTING, OPEN_REPARSE_POINT.
    # The source is this operation's exclusive, completed staging file.
    handle = create(str(source), 0x10080, 7, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        status = rename(handle, ctypes.byref(IoStatus()), buffer, size, 10)
        if status < 0:
            raise ctypes.WinError(error_code(status))
    finally:
        close(handle)
