"""Compose local dataset sinks, publication and read adapters."""

from pulsecrawl.adapters.outbound.filesystem.atomic import (
    _atomic_json,
    _fsync_directory,
    _contained_path,
    _persistable_headers,
)
from pulsecrawl.adapters.outbound.filesystem.manifests import LocalManifestStore
from pulsecrawl.adapters.outbound.filesystem.pages import JsonPageSink
from pulsecrawl.adapters.outbound.filesystem.dataset_files import DatasetFiles
from pulsecrawl.adapters.outbound.sqlite.records import SQLiteRecordStage
from pulsecrawl.adapters.outbound.sqlite.history import SQLiteURLHistory
from pulsecrawl.adapters.outbound.parquet.publication import ParquetExecutionWriter
from pulsecrawl.adapters.outbound.parquet.compaction import ParquetCompactor
from pulsecrawl.adapters.outbound.duckdb.query import (
    DuckDBDatasetQuery,
    validate_select_only,
    _configure_duckdb,
    _lock_down_duckdb,
)
from pulsecrawl.application.datasets.publication import (
    DatasetPublicationService,
    DatasetCompactionService,
)
from pulsecrawl.domain.datasets.identity import normalize_url_identity
import os  # Legacy fault-injection hooks target this shared standard-library module.

__all__ = [
    "LocalDatasetReader",
    "LocalDatasetWriter",
    "LocalManifestStore",
    "normalize_url_identity",
    "validate_select_only",
    "_configure_duckdb",
    "_lock_down_duckdb",
    "_atomic_json",
    "_fsync_directory",
    "_contained_path",
    "_persistable_headers",
    "os",
]


class LocalDatasetWriter:
    def __init__(self, **kwargs):
        self._stage = SQLiteRecordStage(**kwargs)
        self.execution_id = self._stage.execution_id
        self._pages = JsonPageSink(
            self._stage.execution_dir, self._stage.store_raw_pages
        )
        self._publication = DatasetPublicationService(
            ParquetExecutionWriter(self._stage),
            LocalManifestStore(
                self._stage.dataset_dir, self._stage.dataset_id, self._stage.state
            ),
        )

    @property
    def rows_written(self):
        return self._stage.rows_written

    async def save(self, hashed, snapshot):
        await self._pages.save(hashed, snapshot)

    async def emit(self, records):
        await self._stage.emit(records)

    def finalize(self, *, completed_at=None):
        return self._publication.publish(
            change_id=self._stage.execution_id, completed_at=completed_at
        )


class LocalDatasetReader:
    def __init__(self, state, workspace, definition):
        self.state, self.workspace, self.definition = state, workspace, definition
        self.dataset_id = str(definition["datasetId"])
        self._files = DatasetFiles(state, workspace, definition)
        self.dataset_dir, self.manifests = (
            self._files.dataset_dir,
            self._files.manifests,
        )
        self._query = DuckDBDatasetQuery(self._files)
        self._history = SQLiteURLHistory(state, self.dataset_id)
        self._compaction = DatasetCompactionService(ParquetCompactor(self._files))

    def files(self, *, version=None):
        return self._files.files(version=version)

    def _paths(self, version=None):
        return self._files._paths(version)

    def validate_files(self, *, version=None):
        return self._files.validate_files(version=version)

    def query(self, *args, **kwargs):
        return self._query.query(*args, **kwargs)

    def urls(self, **filters):
        return self._history.urls(**filters)

    def execution_urls(self, execution_id, **filters):
        return self._query.execution_urls(execution_id, **filters)

    def compact(self, *, minimum_files=2):
        return self._compaction.compact(minimum_files=minimum_files)
