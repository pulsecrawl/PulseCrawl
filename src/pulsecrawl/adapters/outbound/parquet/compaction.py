"""Filesystem Parquet datasets, versioned manifests, and local URL history."""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from pathlib import Path
from typing import Any


from pulsecrawl.adapters.outbound.filesystem.atomic import _fsync_directory


class ParquetCompactor:
    def __init__(self, files):
        self.manifests, self.dataset_dir = files.manifests, files.dataset_dir

    def compact(self, *, minimum_files: int = 2) -> int:
        if isinstance(minimum_files, bool) or minimum_files < 2:
            raise ValueError("minimum_files must be at least 2")
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as missing:  # pragma: no cover
            raise ImportError(
                "workspace compaction needs PyArrow: pip install 'pulsecrawl[workspace]'"
            ) from missing
        current = self.manifests.current()
        groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for item in current.get("files", []):
            groups[(item.get("ingestDate"), int(item.get("ingestHour", 0)))].append(
                item
            )
        replacements: dict[str, dict[str, Any]] = {}
        remove: set[str] = set()
        for (day, hour), items in sorted(groups.items()):
            if len(items) < minimum_files:
                continue
            parquet_files = [
                pq.ParquetFile(self.dataset_dir / item["path"]) for item in items
            ]
            schema = pa.unify_schemas([source.schema_arrow for source in parquet_files])
            digest = hashlib.sha256(
                "\n".join(sorted(item["path"] for item in items)).encode()
            ).hexdigest()[:20]
            relative = (
                Path("data")
                / f"ingest_date={day}"
                / f"hour={hour:02d}"
                / f"compact-{digest}.parquet"
            )
            target = self.dataset_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.tmp")
            writer = pq.ParquetWriter(
                temporary, schema, compression="zstd", write_statistics=True
            )
            row_count = 0
            minimum_crawled = None
            maximum_crawled = None
            try:
                for source in parquet_files:
                    for batch in source.iter_batches(batch_size=100_000):
                        table = pa.Table.from_batches([batch])
                        arrays = []
                        for field in schema:
                            if field.name in table.column_names:
                                column = table[field.name]
                                if column.type != field.type:
                                    column = column.cast(field.type)
                            else:
                                column = pa.chunked_array(
                                    [pa.nulls(table.num_rows, type=field.type)]
                                )
                            arrays.append(column)
                        aligned = pa.Table.from_arrays(arrays, schema=schema)
                        if "_crawled_at" in aligned.column_names:
                            for value in aligned["_crawled_at"].to_pylist():
                                if value is not None:
                                    minimum_crawled = (
                                        value
                                        if minimum_crawled is None
                                        else min(minimum_crawled, value)
                                    )
                                    maximum_crawled = (
                                        value
                                        if maximum_crawled is None
                                        else max(maximum_crawled, value)
                                    )
                        writer.write_table(aligned, row_group_size=100_000)
                        row_count += aligned.num_rows
            except BaseException:
                writer.close()
                temporary.unlink(missing_ok=True)
                raise
            else:
                writer.close()
            with temporary.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            _fsync_directory(target.parent)
            replacements[relative.as_posix()] = {
                "path": relative.as_posix(),
                "kind": "compact",
                "executionId": None,
                "ingestDate": day,
                "ingestHour": hour,
                "rows": row_count,
                "sizeBytes": target.stat().st_size,
                "minCrawledAt": str(minimum_crawled) if minimum_crawled else None,
                "maxCrawledAt": str(maximum_crawled) if maximum_crawled else None,
            }
            remove.update(item["path"] for item in items)
        if not replacements:
            return 0
        updated = self.manifests.replace_files(
            remove, tuple(replacements.values()), change_id="compact"
        )
        active_paths = {item["path"] for item in updated.get("files", [])}
        return sum(path in active_paths for path in replacements)
