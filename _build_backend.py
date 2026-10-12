"""Setuptools hooks with identity-free, deterministic source archive headers.

This backend is included in the sdist so ordinary PEP 517 builds (including
builds from the sdist) apply the same policy without a separate release command.
"""

from __future__ import annotations

import gzip
import os
from pathlib import Path
import tarfile
import tempfile

from setuptools import build_meta as _backend

build_wheel = _backend.build_wheel
build_editable = _backend.build_editable
get_requires_for_build_wheel = _backend.get_requires_for_build_wheel
get_requires_for_build_sdist = _backend.get_requires_for_build_sdist
get_requires_for_build_editable = _backend.get_requires_for_build_editable
prepare_metadata_for_build_wheel = _backend.prepare_metadata_for_build_wheel
prepare_metadata_for_build_editable = _backend.prepare_metadata_for_build_editable


def _neutralize_sdist(path: Path) -> None:
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    if epoch < 0:
        raise ValueError("SOURCE_DATE_EPOCH must be non-negative")
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tar.gz")
    try:
        with os.fdopen(fd, "wb") as raw, gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, mtime=epoch
        ) as compressed, tarfile.open(fileobj=compressed, mode="w") as target:
            with tarfile.open(path, "r:gz") as source:
                for member in source:
                    if not (member.isfile() or member.isdir()):
                        raise ValueError("sdist must contain only files and directories")
                    body = source.extractfile(member) if member.isfile() else None
                    member.uid = member.gid = 0
                    member.uname = member.gname = ""
                    member.mtime = epoch
                    member.mode = 0o755 if member.isdir() else 0o644
                    member.pax_headers = {}
                    target.addfile(member, body)
                    if body is not None:
                        body.close()
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def build_sdist(sdist_directory, config_settings=None):
    name = _backend.build_sdist(sdist_directory, config_settings)
    _neutralize_sdist(Path(sdist_directory) / name)
    return name
