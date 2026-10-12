"""Backup, restore, retention, health, and repair for local workspaces."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from pulsecrawl.adapters.outbound.filesystem.atomic import _fsync_directory


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _durable_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    with target.open("rb") as handle:
        os.fsync(handle.fileno())
    _fsync_directory(target.parent)
