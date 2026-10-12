"""Durability must not depend on POSIX read-only descriptor semantics."""

import os
from pathlib import Path

import pytest

from pulsecrawl.adapters.outbound.filesystem.atomic import _fsync_file
from pulsecrawl.adapters.outbound.filesystem.backup_io import _durable_copy


def test_completed_file_flush_uses_writable_handle_without_truncating(tmp_path, monkeypatch):
    path = tmp_path / "output.parquet"
    path.write_bytes(b"completed output")
    original_open = Path.open
    modes = []

    def opened(target, mode="r", *args, **kwargs):
        if target == path:
            modes.append(mode)
        return original_open(target, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    _fsync_file(path)
    assert modes == ["r+b"]
    assert path.read_bytes() == b"completed output"


def test_file_flush_errors_are_not_silently_ignored(tmp_path, monkeypatch):
    path = tmp_path / "output"
    path.write_bytes(b"output")

    def fail(_descriptor):
        raise OSError("device flush failed")

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError, match="device flush failed"):
        _fsync_file(path)


def test_backup_flushes_before_preserving_readonly_permissions(tmp_path):
    source, target = tmp_path / "source", tmp_path / "backup"
    source.write_bytes(b"read-only source")
    source.chmod(0o444)
    try:
        _durable_copy(source, target)
        assert target.read_bytes() == source.read_bytes()
        if os.name != "nt":
            assert target.stat().st_mode & 0o777 == 0o444
    finally:
        source.chmod(0o600)
        if target.exists():
            target.chmod(0o600)
