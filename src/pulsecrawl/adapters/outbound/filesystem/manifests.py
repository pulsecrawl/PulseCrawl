"""Filesystem Parquet datasets, versioned manifests, and local URL history."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from pulsecrawl.domain.errors import (
    DatasetCorruptionError,
)
from pulsecrawl.adapters.outbound.sqlite.state import SQLiteState
from pulsecrawl.adapters.outbound.sqlite.clock import utc_now

from pulsecrawl.adapters.outbound.filesystem.atomic import _atomic_json, _contained_path


class LocalManifestStore:
    """Immutable dataset versions with an atomically replaced current pointer.

    New manifests live in ``manifests/versions``. Legacy ``snapshots`` paths
    and pointer keys remain readable without moving existing workspace files.
    """

    def __init__(self, dataset_dir: Path, dataset_id: str, state: SQLiteState) -> None:
        self.dataset_dir = dataset_dir
        self.dataset_id = dataset_id
        self.state = state
        self.current_path = dataset_dir / "manifests" / "current.json"

    def _validated_manifest(
        self, manifest: object, *, expected_version: int | None = None
    ) -> dict[str, Any]:
        if not isinstance(manifest, dict):
            raise DatasetCorruptionError(
                "dataset version manifest must be a JSON object"
            )
        if manifest.get("schemaVersion") != 1:
            raise DatasetCorruptionError("unsupported dataset version manifest format")
        if manifest.get("datasetId") != self.dataset_id:
            raise DatasetCorruptionError("dataset version belongs to another dataset")
        version = manifest.get("version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise DatasetCorruptionError("dataset version number is invalid")
        if expected_version is not None and version != expected_version:
            raise DatasetCorruptionError("dataset pointer/manifest mismatch")
        files = manifest.get("files")
        if not isinstance(files, list):
            raise DatasetCorruptionError("dataset version files must be a list")
        seen: set[str] = set()
        for item in files:
            if not isinstance(item, dict):
                raise DatasetCorruptionError("dataset version file entry is invalid")
            path = item.get("path")
            if not isinstance(path, str) or not path:
                raise DatasetCorruptionError("dataset version file path is invalid")
            if path in seen:
                raise DatasetCorruptionError(f"duplicate dataset file path: {path}")
            seen.add(path)
            for key in ("rows", "sizeBytes"):
                value = item.get(key)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise DatasetCorruptionError(
                        f"dataset version {key} is invalid for {path}"
                    )
        return manifest

    def _manifest_path(self, relative: object) -> Path:
        path = _contained_path(self.dataset_dir, relative, kind="version manifest")
        parents = {
            (self.dataset_dir / "manifests" / directory).resolve()
            for directory in ("versions", "snapshots")
        }
        if path.parent not in parents or path.suffix != ".json":
            raise DatasetCorruptionError(
                f"unsafe dataset version manifest path: {relative}"
            )
        return path

    def version_paths(self) -> list[Path]:
        """List both new and legacy manifests in dataset-version order."""
        paths = (
            path
            for directory in ("versions", "snapshots")
            for path in (self.dataset_dir / "manifests" / directory).glob("*.json")
        )
        return sorted(
            (
                self._manifest_path(path.relative_to(self.dataset_dir).as_posix())
                for path in paths
            ),
            key=lambda path: (path.name, path.parent.name),
        )

    def current(self) -> dict[str, Any]:
        if not self.current_path.exists():
            return {
                "schemaVersion": 1,
                "datasetId": self.dataset_id,
                "version": 0,
                "files": [],
            }
        pointer = json.loads(self.current_path.read_text())
        if pointer.get("datasetId") != self.dataset_id:
            raise DatasetCorruptionError(
                "dataset manifest pointer belongs to another dataset"
            )
        if (
            "manifest" in pointer
            and "snapshot" in pointer
            and pointer["manifest"] != pointer["snapshot"]
        ):
            raise DatasetCorruptionError(
                "dataset pointer has conflicting manifest and legacy snapshot paths"
            )
        manifest_value = pointer.get("manifest", pointer.get("snapshot"))
        manifest_path = self._manifest_path(manifest_value)
        manifest = json.loads(manifest_path.read_text())
        return self._validated_manifest(
            manifest, expected_version=pointer.get("version")
        )

    def at_version(self, version: int | None) -> dict[str, Any]:
        if version is None:
            return self.current()
        matches = [
            path
            for path in self.version_paths()
            if path.name.startswith(f"{version:020d}-")
        ]
        if len(matches) != 1:
            raise KeyError(f"dataset version {version} is missing or ambiguous")
        return self._validated_manifest(
            json.loads(matches[0].read_text()), expected_version=version
        )

    def publish(
        self,
        files: Sequence[Mapping[str, Any]],
        *,
        change_id: str,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        created_at = created_at or utc_now()
        safe_change = re.sub(r"[^A-Za-z0-9_.-]+", "-", change_id).strip("-")
        with self.state.transaction():
            current = self.current()
            return self._publish_locked(
                current, files, safe_change=safe_change, created_at=created_at
            )

    def _publish_locked(
        self,
        current: Mapping[str, Any],
        files: Sequence[Mapping[str, Any]],
        *,
        safe_change: str,
        created_at: str,
    ) -> dict[str, Any]:
        version = int(current.get("version", 0)) + 1
        relative = (
            Path("manifests") / "versions" / (f"{version:020d}-{safe_change}.json")
        )
        manifest = {
            "schemaVersion": 1,
            "datasetId": self.dataset_id,
            "version": version,
            "createdAt": created_at,
            "files": sorted((dict(item) for item in files), key=lambda x: x["path"]),
        }
        _atomic_json(self.dataset_dir / relative, manifest)
        _atomic_json(
            self.current_path,
            {
                "schemaVersion": 1,
                "datasetId": self.dataset_id,
                "version": version,
                "manifest": relative.as_posix(),
                "updatedAt": created_at,
            },
        )
        return manifest

    def add_file(self, item: Mapping[str, Any], *, change_id: str) -> dict[str, Any]:
        with self.state.transaction():
            current = self.current()
            files = {entry["path"]: dict(entry) for entry in current.get("files", [])}
            existing = files.get(item["path"])
            if existing is not None:
                if existing != dict(item):
                    raise RuntimeError(
                        f"immutable dataset file changed: {item['path']}"
                    )
                return current
            files[item["path"]] = dict(item)
            return self._publish_locked(
                current,
                tuple(files.values()),
                safe_change=re.sub(r"[^A-Za-z0-9_.-]+", "-", change_id).strip("-"),
                created_at=utc_now(),
            )

    def replace_files(
        self,
        remove: set[str],
        replacements: Sequence[Mapping[str, Any]],
        *,
        change_id: str,
    ) -> dict[str, Any]:
        """CAS-like compaction transform preserving concurrently added deltas."""
        with self.state.transaction():
            current = self.current()
            current_paths = {item["path"] for item in current.get("files", [])}
            if not remove.issubset(current_paths):
                return current
            files = [
                dict(item)
                for item in current.get("files", [])
                if item["path"] not in remove
            ]
            files.extend(dict(item) for item in replacements)
            return self._publish_locked(
                current,
                files,
                safe_change=re.sub(r"[^A-Za-z0-9_.-]+", "-", change_id).strip("-"),
                created_at=utc_now(),
            )
