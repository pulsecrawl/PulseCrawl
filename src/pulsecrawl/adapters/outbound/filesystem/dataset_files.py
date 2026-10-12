"""Filesystem Parquet datasets, versioned manifests, and local URL history."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from pulsecrawl.domain.errors import (
    DatasetCorruptionError,
)
from pulsecrawl.adapters.outbound.sqlite.state import SQLiteState

from pulsecrawl.adapters.outbound.filesystem.atomic import _contained_path
from pulsecrawl.adapters.outbound.filesystem.manifests import LocalManifestStore


class DatasetFiles:
    def __init__(
        self, state: SQLiteState, workspace: Path, definition: Mapping[str, Any]
    ):
        self.state = state
        self.workspace = workspace
        self.definition = definition
        self.dataset_id = str(definition["datasetId"])
        self.dataset_dir = workspace / "datasets" / self.dataset_id
        self.manifests = LocalManifestStore(self.dataset_dir, self.dataset_id, state)

    def files(self, *, version: int | None = None) -> list[dict[str, Any]]:
        return list(self.manifests.at_version(version).get("files", []))

    def _paths(self, version: int | None = None) -> list[Path]:
        paths: list[Path] = []
        data_root = (self.dataset_dir / "data").resolve()
        for item in self.files(version=version):
            relative = item.get("path")
            path = _contained_path(self.dataset_dir, relative, kind="data file")
            try:
                path.relative_to(data_root)
            except ValueError as exc:
                raise DatasetCorruptionError(
                    f"dataset file is outside the data directory: {relative}"
                ) from exc
            if path.suffix != ".parquet" or (path.exists() and not path.is_file()):
                raise DatasetCorruptionError(
                    f"dataset file must be a regular parquet file: {relative}"
                )
            paths.append(path)
        missing = [str(path) for path in paths if not path.exists()]
        if missing:
            raise DatasetCorruptionError(f"active dataset files are missing: {missing}")
        return paths

    def validate_files(self, *, version: int | None = None) -> list[Path]:
        """Validate active file size, Parquet metadata, and manifest row counts."""
        items = self.files(version=version)
        paths = self._paths(version)
        if not paths:
            return paths
        try:
            import pyarrow.parquet as pq
        except ImportError as missing:  # pragma: no cover - installation guard
            raise ImportError(
                "workspace validation needs PyArrow: pip install 'pulsecrawl[workspace]'"
            ) from missing
        for item, path in zip(items, paths, strict=True):
            actual_size = path.stat().st_size
            if actual_size != item["sizeBytes"]:
                raise DatasetCorruptionError(
                    f"dataset file size mismatch for {item['path']}: "
                    f"expected {item['sizeBytes']}, got {actual_size}"
                )
            try:
                actual_rows = pq.ParquetFile(path).metadata.num_rows
            except Exception as exc:
                raise DatasetCorruptionError(
                    f"dataset file is not readable Parquet: {item['path']}"
                ) from exc
            if actual_rows != item["rows"]:
                raise DatasetCorruptionError(
                    f"dataset row count mismatch for {item['path']}: "
                    f"expected {item['rows']}, got {actual_rows}"
                )
        return paths
