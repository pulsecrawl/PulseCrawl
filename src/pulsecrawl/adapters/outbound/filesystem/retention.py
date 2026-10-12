"""Backup, restore, retention, health, and repair for local workspaces."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pulsecrawl.domain.errors import DatasetCorruptionError
from pulsecrawl.adapters.outbound.filesystem.atomic import (
    _atomic_json,
    _fsync_directory,
)
from pulsecrawl.adapters.outbound.sqlite.clock import utc_now

from pulsecrawl.adapters.outbound.filesystem.backup_io import _inside


class LocalRetentionAdapter:
    def __init__(self, *, root, state, datasets, readers, validate, lock):
        self.root, self.state, self.datasets = root, state, datasets
        self.readers, self.validate, self.lock = readers, validate, lock

    def prune_dataset(
        self,
        dataset_id: str,
        *,
        keep_versions: int | None = None,
        keep_snapshots: int | None = None,
        older_than_days: int | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        if keep_versions is None:
            keep_versions = keep_snapshots if keep_snapshots is not None else 30
        elif keep_snapshots is not None and keep_snapshots != keep_versions:
            raise ValueError("keep_versions and legacy keep_snapshots disagree")
        if keep_versions < 1:
            raise ValueError("keep_versions must be at least 1")
        if older_than_days is not None and older_than_days < 1:
            raise ValueError("older_than_days must be positive")
        if not dry_run:
            with self.lock():
                report = self.prune_dataset(
                    dataset_id,
                    keep_versions=keep_versions,
                    older_than_days=older_than_days,
                    dry_run=True,
                )
                report["dryRun"] = False
                root = self.root / "datasets" / dataset_id
                journal = root / "manifests" / "prune-journal.json"
                _atomic_json(journal, report)
                for relative in report["versionsDeleted"]:
                    target = (root / relative).resolve()
                    if not _inside(target, root.resolve()):
                        raise DatasetCorruptionError(
                            f"unsafe dataset version prune path: {relative}"
                        )
                    target.unlink(missing_ok=True)
                for relative in report["filesDeleted"]:
                    target = (root / relative).resolve()
                    if not _inside(target, root.resolve()):
                        raise DatasetCorruptionError(
                            f"unsafe dataset prune path: {relative}"
                        )
                    target.unlink(missing_ok=True)
                journal.unlink(missing_ok=True)
                _fsync_directory(root / "manifests")
                return report
        dataset = self.datasets.get(dataset_id)
        root = self.root / "datasets" / dataset_id
        manifests = self.readers(dataset).manifests
        versions = manifests.version_paths()
        current = manifests.current()
        current_version = int(current.get("version", 0))
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=older_than_days)
            if older_than_days is not None
            else None
        )
        retained: list[Path] = []
        deleted_versions: list[Path] = []
        for index, path in enumerate(versions):
            value = json.loads(path.read_text(encoding="utf-8"))
            keep_recent = index >= max(0, len(versions) - keep_versions)
            created = datetime.fromisoformat(
                str(value.get("createdAt", utc_now())).replace("Z", "+00:00")
            )
            keep_by_age = cutoff is not None and created >= cutoff
            if (
                int(value.get("version", -1)) == current_version
                or keep_recent
                or keep_by_age
            ):
                retained.append(path)
            else:
                deleted_versions.append(path)
        referenced: set[str] = set()
        for path in retained:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            referenced.update(str(item["path"]) for item in manifest.get("files", []))
        data_files = [item for item in (root / "data").rglob("*") if item.is_file()]
        orphaned = [
            path
            for path in data_files
            if path.relative_to(root).as_posix() not in referenced
        ]
        report = {
            "datasetId": dataset_id,
            "dryRun": dry_run,
            "versionsDeleted": [
                path.relative_to(root).as_posix() for path in deleted_versions
            ],
            # Retained for callers using the original report vocabulary.
            "snapshotsDeleted": [path.name for path in deleted_versions],
            "filesDeleted": [path.relative_to(root).as_posix() for path in orphaned],
            "bytesReclaimed": sum(path.stat().st_size for path in orphaned),
        }
        return report
