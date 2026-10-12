"""Restore/backup must never replace or remove a competing destination."""

from pathlib import Path

import pytest

from pulsecrawl import Workspace
from pulsecrawl.adapters.outbound.filesystem import backups
from pulsecrawl.adapters.outbound.filesystem.publication import publish_directory
from pulsecrawl.errors import DatasetCorruptionError


@pytest.mark.parametrize("kind", ["empty", "nonempty", "file", "symlink"])
def test_directory_publication_never_clobbers_existing_target(tmp_path, kind):
    source, destination = tmp_path / "temporary", tmp_path / "destination"
    source.mkdir()
    (source / "data").write_text("new")
    if kind in ("empty", "nonempty"):
        destination.mkdir()
        if kind == "nonempty":
            (destination / "original").write_text("keep")
    elif kind == "file":
        destination.write_text("keep")
    else:
        try:
            destination.symlink_to(tmp_path / "missing", target_is_directory=True)
        except OSError:
            pytest.skip("symlink creation requires platform privileges")
    original = destination.lstat()
    with pytest.raises(OSError):
        publish_directory(source, destination)
    assert destination.lstat().st_ino == original.st_ino
    assert (source / "data").read_text() == "new"
    if kind == "nonempty":
        assert (destination / "original").read_text() == "keep"


def test_directory_publication_moves_complete_directory(tmp_path):
    source, destination = tmp_path / "temporary", tmp_path / "destination"
    source.mkdir()
    (source / "data").write_text("complete")
    publish_directory(source, destination)
    assert not source.exists()
    assert (destination / "data").read_text() == "complete"


@pytest.fixture
def backup(tmp_path):
    with Workspace.init(tmp_path / "workspace") as workspace:
        workspace.maintenance.backup(tmp_path / "backup")
    return tmp_path / "backup"


@pytest.mark.parametrize("nonempty", [False, True])
def test_restore_preserves_destination_created_while_copying(
    backup, tmp_path, monkeypatch, nonempty
):
    destination = tmp_path / "restored"
    copy = backups._durable_copy

    def competing_copy(source, target):
        copy(source, target)
        if not destination.exists():
            destination.mkdir()
            if nonempty:
                (destination / "original").write_text("keep")

    monkeypatch.setattr(backups, "_durable_copy", competing_copy)
    with pytest.raises(OSError):
        backups.LocalBackupAdapter.restore(
            backup, destination, lambda _: ({"valid": True}, ["ok"])
        )
    assert destination.is_dir()
    if nonempty:
        assert (destination / "original").read_text() == "keep"
    assert not list(tmp_path.glob(".restored.*"))


@pytest.mark.parametrize("validation,integrity", [
    ({"valid": False, "errors": ["invalid"]}, ["ok"]),
    ({"valid": True}, ["corruption"]),
])
def test_invalid_restore_is_never_published(backup, tmp_path, validation, integrity):
    destination = tmp_path / "restored"

    def validate(path):
        assert Path(path) != destination
        assert not destination.exists()
        return validation, integrity

    with pytest.raises(DatasetCorruptionError):
        backups.LocalBackupAdapter.restore(backup, destination, validate)
    assert not destination.exists()
    assert not list(tmp_path.glob(".restored.*"))


def test_failed_validation_never_deletes_competing_target(backup, tmp_path):
    destination = tmp_path / "restored"

    def validate(_path):
        destination.mkdir()
        (destination / "original").write_text("keep")
        raise RuntimeError("validation failed")

    with pytest.raises(RuntimeError, match="validation failed"):
        backups.LocalBackupAdapter.restore(backup, destination, validate)
    assert (destination / "original").read_text() == "keep"
