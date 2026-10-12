"""Local dataset storage mirroring the cloud layout.

A local dataset is a folder; each run appends an execution underneath:

    <dataset>/executions/<executionId>/pages/{urlHash}.json
    <dataset>/executions/<executionId>/records-000.jsonl
    <dataset>/executions/<executionId>/_manifest.json   (written last)

Query it all with DuckDB exactly like the hosted product:
    SELECT * FROM read_json_auto('<dataset>/executions/*/records-*.jsonl')
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from pulsecrawl.adapters.outbound.filesystem.atomic import (
    _atomic_json,
    _fsync_directory,
    _persistable_headers,
)

RECORDS_CHUNK_SIZE = 500
RECORDS_CHUNK_BYTES = 4 * 1024 * 1024
_SAFE_EXECUTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,255}$")


def new_execution_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")
    return f"exec_{stamp}_{secrets.token_hex(10)}"


class LocalExecutionWriter:
    """Filesystem PageSink + RecordSink for one execution."""

    def __init__(
        self, dataset_path: str | Path, *, execution_id: str | None = None
    ) -> None:
        self.dataset_path = Path(dataset_path)
        self.execution_id = execution_id or new_execution_id()
        if not _SAFE_EXECUTION_ID.fullmatch(self.execution_id):
            raise ValueError("execution_id contains unsafe path characters")
        self.execution_dir = self.dataset_path / "executions" / self.execution_id
        self._pages_dir = self.execution_dir / "pages"
        self._buffer: list[str] = []
        self._buffer_bytes = 0
        self._chunk = 0
        self.rows_written = 0

    # PageSink port -----------------------------------------------------------
    async def save(self, url_hash: str, snapshot) -> None:
        self._pages_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "url": snapshot.url,
            "finalUrl": snapshot.final_url,
            "status": snapshot.status,
            "headers": _persistable_headers(snapshot.headers),
            "body": snapshot.body,
            "depth": snapshot.depth,
            "fetchedAt": snapshot.fetched_at.isoformat(),
            "bodyTruncated": snapshot.body_truncated,
            "bodyBytes": snapshot.body_bytes,
        }
        _atomic_json(self._pages_dir / f"{url_hash}.json", payload)

    # RecordSink port ---------------------------------------------------------
    async def emit(self, records: Sequence) -> None:
        for record in records:
            row = {
                **record.fields,
                "_execution_id": self.execution_id,
                "_template_id": record.template_id,
                "_template_origin": record.template_origin,
                "_match_tier": record.match_tier,
                "_source_url": record.source_url,
                "_crawled_at": record.fetched_at.isoformat(),
            }
            encoded = json.dumps(row, sort_keys=True)
            self._buffer.append(encoded)
            self._buffer_bytes += len(encoded.encode("utf-8")) + 1
        if (
            len(self._buffer) >= RECORDS_CHUNK_SIZE
            or self._buffer_bytes >= RECORDS_CHUNK_BYTES
        ):
            self._flush()

    def _flush(self) -> None:
        if not self._buffer:
            return
        self.execution_dir.mkdir(parents=True, exist_ok=True)
        path = self.execution_dir / f"records-{self._chunk:03d}.jsonl"
        if path.exists():
            raise FileExistsError(f"refusing to overwrite record chunk: {path}")
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write("\n".join(self._buffer) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            _fsync_directory(path.parent)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        self.rows_written += len(self._buffer)
        self._buffer = []
        self._buffer_bytes = 0
        self._chunk += 1

    def finalize(
        self,
        *,
        stats: dict,
        engine: str | None,
        mappings,
        templates=None,
        system_templates=None,
        fields,
    ) -> Path:
        """Flush and write the manifest: its presence marks the run complete."""
        self._flush()
        self.execution_dir.mkdir(parents=True, exist_ok=True)
        if templates is None:
            authored_templates = [
                {
                    "engine": engine,
                    "mappings": {
                        key: list(value)
                        if isinstance(value, (list, tuple))
                        else [value]
                        for key, value in dict(mappings).items()
                    },
                }
            ]
        else:
            authored_templates = list(templates)
        manifest = {
            "executionId": self.execution_id,
            "stats": stats,
            "templates": authored_templates,
            "systemTemplates": list(system_templates or ()),
            "fields": list(fields),
            "recordChunks": self._chunk,
            "completedAt": datetime.now(timezone.utc).isoformat(),
        }
        path = self.execution_dir / "_manifest.json"
        if path.exists():
            raise FileExistsError(f"refusing to overwrite execution manifest: {path}")
        _atomic_json(path, manifest)
        return path
