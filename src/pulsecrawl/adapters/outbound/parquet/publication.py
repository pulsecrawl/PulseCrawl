"""Filesystem Parquet datasets, versioned manifests, and local URL history."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from pulsecrawl.adapters.outbound.sqlite.clock import utc_now

from pulsecrawl.adapters.outbound.filesystem.atomic import _fsync_directory, _fsync_file


class ParquetExecutionWriter:
    def __init__(self, stage):
        self.stage = stage
        self.dataset = stage.dataset
        self.dataset_dir = stage.dataset_dir
        self.execution_id = stage.execution_id

    def write(self, *, completed_at: str | None = None) -> dict[str, Any] | None:
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as missing:  # pragma: no cover - installation guard
            raise ImportError(
                "workspace datasets need PyArrow: pip install 'pulsecrawl[workspace]'"
            ) from missing
        datetime_fields = {
            field["name"]
            for field in self.dataset.get("fields", [])
            if field.get("type") == "datetime"
        }
        datetime_fields.update(
            {
                "_crawled_at",
                "_execution_started_at",
                "_scheduled_for",
                "_first_seen_at",
                "_last_seen_at",
            }
        )
        arrow_types = {
            "string": pa.string(),
            "number": pa.float64(),
            "boolean": pa.bool_(),
            "datetime": pa.timestamp("us", tz="UTC"),
            "url": pa.string(),
        }
        provenance = [
            ("_job_id", pa.string()),
            ("_execution_id", pa.string()),
            ("_template_id", pa.string()),
            ("_template_origin", pa.string()),
            ("_match_tier", pa.string()),
            ("_schema_id", pa.string()),
            ("_source_url", pa.string()),
            ("_crawled_at", pa.timestamp("us", tz="UTC")),
            ("_execution_started_at", pa.timestamp("us", tz="UTC")),
            ("_scheduled_for", pa.timestamp("us", tz="UTC")),
            ("_url_identity", pa.string()),
            ("_is_new_url", pa.bool_()),
            ("_first_seen_at", pa.timestamp("us", tz="UTC")),
            ("_last_seen_at", pa.timestamp("us", tz="UTC")),
            ("_seen_count", pa.int64()),
        ]
        schema = pa.schema(
            [
                (str(field["name"]), arrow_types[str(field["type"])])
                for field in self.dataset.get("fields", [])
            ]
            + provenance
        )
        # Partition by ingestion/completion time.  `_crawled_at` remains the
        # exact HTTP-request timestamp used for notification windows.  Keeping
        # those concepts separate prevents a long execution from being filed
        # under the hour of its first request.
        ingested_at = completed_at or utc_now()
        partition_time = datetime.fromisoformat(ingested_at.replace("Z", "+00:00"))
        relative = (
            Path("data")
            / f"ingest_date={partition_time.date().isoformat()}"
            / f"hour={partition_time.hour:02d}"
            / f"delta-{self.execution_id}.parquet"
        )
        target = self.dataset_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        row_count = 0
        minimum_crawled: datetime | None = None
        maximum_crawled: datetime | None = None
        parquet = None
        try:
            for rows in self.stage.batches():
                for row in rows:
                    for name in datetime_fields:
                        value = row.get(name)
                        if isinstance(value, str) and value:
                            row[name] = datetime.fromisoformat(
                                value.replace("Z", "+00:00")
                            )
                    crawled = row.get("_crawled_at")
                    if isinstance(crawled, datetime):
                        minimum_crawled = (
                            crawled
                            if minimum_crawled is None
                            else min(minimum_crawled, crawled)
                        )
                        maximum_crawled = (
                            crawled
                            if maximum_crawled is None
                            else max(maximum_crawled, crawled)
                        )
                table = pa.Table.from_pylist(rows, schema=schema)
                if parquet is None:
                    parquet = pq.ParquetWriter(
                        temporary,
                        schema,
                        compression="zstd",
                        write_statistics=True,
                    )
                parquet.write_table(table, row_group_size=100_000)
                row_count += table.num_rows
        except BaseException:
            if parquet is not None:
                parquet.close()
                parquet = None
            temporary.unlink(missing_ok=True)
            raise
        finally:
            if parquet is not None:
                parquet.close()
        if row_count == 0:
            temporary.unlink(missing_ok=True)
            return None
        _fsync_file(temporary)
        os.replace(temporary, target)
        _fsync_directory(target.parent)
        item = {
            "path": relative.as_posix(),
            "kind": "delta",
            "executionId": self.execution_id,
            "ingestDate": partition_time.date().isoformat(),
            "ingestHour": partition_time.hour,
            "rows": row_count,
            "sizeBytes": target.stat().st_size,
            "minCrawledAt": str(minimum_crawled) if minimum_crawled else None,
            "maxCrawledAt": str(maximum_crawled) if maximum_crawled else None,
        }
        return item
