"""Filesystem Parquet datasets, versioned manifests, and local URL history."""

from __future__ import annotations

import errno
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

from pulsecrawl.domain.errors import (
    DatasetCorruptionError,
    InsufficientStorageError,
    WorkspaceReadOnlyError,
)

_SENSITIVE_RESPONSE_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie"}
)

_REPLACE_ATTEMPTS = 8 if sys.platform == "win32" else 1


def _replace_snapshot(source: str, destination: Path) -> None:
    """Retry bounded Windows sharing conflicts, never delete the destination.

    Concurrent replaces or readers can transiently deny the Windows rename.
    Retry only the already-flushed staging file, for at most 1.27 seconds;
    persistent access denials still reach the caller's normal error mapping.
    """
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, destination)
            return
        except PermissionError as error:
            if (
                getattr(error, "winerror", None) not in {5, 32, 33}
                or attempt + 1 == _REPLACE_ATTEMPTS
            ):
                raise
            time.sleep(0.01 * 2**attempt)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, sort_keys=True, indent=2).encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_snapshot(temporary, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        if exc.errno == errno.ENOSPC:
            raise InsufficientStorageError(
                f"insufficient space writing {path}"
            ) from exc
        if exc.errno in (errno.EACCES, errno.EROFS):
            raise WorkspaceReadOnlyError(f"workspace is not writable: {path}") from exc
        raise
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _fsync_file(path: Path) -> None:
    """Flush an owned output file without truncation, including on Windows.

    Windows' CRT commit operation requires a writable descriptor; reopening a
    completed Parquet or backup file read-only fails with EBADF there.
    """
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    """Persist a same-filesystem rename where directory fsync is supported."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # Windows and some filesystems do not permit directory fsync.
        pass
    finally:
        os.close(descriptor)


def _contained_path(root: Path, relative: object, *, kind: str) -> Path:
    """Resolve an untrusted manifest path without permitting root escape.

    Manifest files are durable local metadata, but they may be copied from a
    backup, manually edited, or corrupted. They must never expand the set of
    files a dataset query is authorized to read.
    """
    if not isinstance(relative, str) or not relative:
        raise DatasetCorruptionError(f"{kind} path must be a non-empty string")
    candidate = Path(relative)
    if candidate.is_absolute():
        raise DatasetCorruptionError(f"unsafe absolute {kind} path: {relative}")
    if ".." in candidate.parts:
        raise DatasetCorruptionError(
            f"unsafe parent traversal in {kind} path: {relative}"
        )
    lexical = root / candidate
    current = root
    for part in candidate.parts:
        current /= part
        if current.is_symlink():
            raise DatasetCorruptionError(
                f"{kind} path must not use symlinks: {relative}"
            )
    root_resolved = root.resolve()
    resolved = lexical.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DatasetCorruptionError(
            f"unsafe {kind} path outside dataset: {relative}"
        ) from exc
    return resolved


def _persistable_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in headers.items()
        if str(key).lower() not in _SENSITIVE_RESPONSE_HEADERS
    }
