"""Backup, restore, retention, health, and repair for local workspaces."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from pulsecrawl.domain.errors import DatasetCorruptionError
from pulsecrawl.adapters.outbound.filesystem.atomic import (
    _atomic_json,
    _fsync_directory,
)
from pulsecrawl.adapters.outbound.sqlite.clock import utc_now
from pulsecrawl.adapters.outbound.filesystem.publication import publish_directory

from pulsecrawl.adapters.outbound.filesystem.backup_io import (
    _inside,
    _sha256,
    _durable_copy,
)


class LocalBackupAdapter:
    def __init__(self, *, root, state, config, lock):
        self.root, self.state, self.config, self.lock = root, state, config, lock

    def backup(
        self, destination: str | Path, *, include_raw_pages: bool = True
    ) -> dict[str, Any]:
        destination = Path(destination).expanduser().resolve()
        if destination.exists():
            raise FileExistsError(f"refusing to overwrite backup: {destination}")
        if _inside(destination, self.root):
            raise ValueError("backup destination must be outside the workspace")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
        )
        try:
            with self.lock():
                for source in sorted(self.root.rglob("*")):
                    relative = source.relative_to(self.root)
                    if not relative.parts or relative.parts[0] in ("cache", "state"):
                        continue
                    if source.is_symlink():
                        raise ValueError(
                            f"workspace backup refuses symlink: {relative}"
                        )
                    if source.is_dir():
                        continue
                    if not include_raw_pages and "pages" in relative.parts:
                        continue
                    if source.name.startswith(".") and source.name.endswith(".tmp"):
                        continue
                    target = temporary / relative
                    _durable_copy(source, target)
                state_target = temporary / "state" / "pulsecrawl.sqlite"
                self.state.backup_to(state_target)
                metadata = {
                    "formatVersion": 1,
                    "createdAt": utc_now(),
                    "workspaceVersion": self.config["workspaceVersion"],
                    "sqliteSchemaVersion": self.state.schema_version,
                    "includeRawPages": include_raw_pages,
                }
                _atomic_json(temporary / "backup.json", metadata)
                checksums = []
                for path in sorted(
                    item for item in temporary.rglob("*") if item.is_file()
                ):
                    if path.name == "checksums.sha256":
                        continue
                    checksums.append(
                        f"{_sha256(path)}  {path.relative_to(temporary).as_posix()}"
                    )
                (temporary / "checksums.sha256").write_text(
                    "\n".join(checksums) + "\n", encoding="utf-8"
                )
                with (temporary / "checksums.sha256").open("rb") as handle:
                    os.fsync(handle.fileno())
                _fsync_directory(temporary)
            publish_directory(temporary, destination)
            _fsync_directory(destination.parent)
            return {
                **metadata,
                "path": str(destination),
                "files": len(checksums),
            }
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    @staticmethod
    def verify_backup(source: str | Path) -> dict[str, Any]:
        root = Path(source).expanduser().resolve()
        checksum_path = root / "checksums.sha256"
        metadata_path = root / "backup.json"
        if not checksum_path.is_file() or not metadata_path.is_file():
            raise DatasetCorruptionError(
                "backup metadata or checksum manifest is missing"
            )
        checked = 0
        listed: set[str] = set()
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            expected, separator, relative = line.partition("  ")
            if not separator or not expected or not relative:
                raise DatasetCorruptionError("backup checksum manifest is malformed")
            if relative in listed:
                raise DatasetCorruptionError(
                    f"duplicate backup checksum entry: {relative}"
                )
            listed.add(relative)
            target = (root / relative).resolve()
            if not _inside(target, root) or target.is_symlink() or not target.is_file():
                raise DatasetCorruptionError(
                    f"backup file is missing or unsafe: {relative}"
                )
            if _sha256(target) != expected:
                raise DatasetCorruptionError(f"backup checksum mismatch: {relative}")
            checked += 1
        actual = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.name != "checksums.sha256"
        }
        if actual != listed:
            raise DatasetCorruptionError("backup contains unlisted or missing files")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("formatVersion") != 1:
            raise DatasetCorruptionError("unsupported backup format")
        return {**metadata, "path": str(root), "files": checked, "valid": True}

    @staticmethod
    def restore(
        source: str | Path, destination: str | Path, validate_restored
    ) -> dict[str, Any]:
        source_path = Path(source).expanduser().resolve()
        destination_path = Path(destination).expanduser().resolve()
        report = LocalBackupAdapter.verify_backup(source_path)
        if _inside(destination_path, source_path):
            raise ValueError("restore destination must be outside the backup")
        if destination_path.exists():
            raise FileExistsError(
                f"refusing to overwrite restore target: {destination_path}"
            )
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{destination_path.name}.", dir=destination_path.parent
            )
        )
        try:
            expected = {}
            for line in (
                (source_path / "checksums.sha256")
                .read_text(encoding="utf-8")
                .splitlines()
            ):
                checksum, _, relative = line.partition("  ")
                expected[relative] = checksum
            for source_file in sorted(source_path.rglob("*")):
                if source_file.is_symlink():
                    raise DatasetCorruptionError("backup contains a symlink")
                if source_file.is_dir() or source_file.name in (
                    "backup.json",
                    "checksums.sha256",
                ):
                    continue
                relative = source_file.relative_to(source_path)
                target = temporary / relative
                _durable_copy(source_file, target)
                relative_text = relative.as_posix()
                if _sha256(target) != expected.get(relative_text):
                    raise DatasetCorruptionError(
                        f"backup changed while restoring: {relative_text}"
                    )
            _fsync_directory(temporary)
            validation, integrity = validate_restored(temporary)
            if not validation["valid"]:
                raise DatasetCorruptionError(
                    "restored workspace failed validation: "
                    + "; ".join(validation["errors"])
                )
            if integrity != ["ok"]:
                raise DatasetCorruptionError(
                    "restored SQLite database failed integrity check"
                )
            publish_directory(temporary, destination_path)
            _fsync_directory(destination_path.parent)
            return {**report, "restoredTo": str(destination_path)}
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
