"""Durable publication ordering, independent of database and file formats."""

from pulsecrawl.application.ports.workspace import RecordFileWriter, ManifestRepository


class DatasetPublicationService:
    def __init__(self, files: RecordFileWriter, manifests: ManifestRepository):
        self._files, self._manifests = files, manifests

    def publish(self, *, change_id, completed_at=None):
        # File durability precedes manifest visibility. A retry uses the same
        # change identity; execution settlement happens only after this returns.
        item = self._files.write(completed_at=completed_at)
        if item is not None:
            self._manifests.add_file(item, change_id=change_id)
        return item


class DatasetCompactionService:
    def __init__(self, compactor):
        self._compactor = compactor

    def compact(self, *, minimum_files=2):
        return self._compactor.compact(minimum_files=minimum_files)
