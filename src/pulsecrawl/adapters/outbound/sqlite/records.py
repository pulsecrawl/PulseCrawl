"""Filesystem Parquet datasets, versioned manifests, and local URL history."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from pulsecrawl.adapters.outbound.sqlite.state import SQLiteState

from pulsecrawl.domain.datasets.identity import normalize_url_identity


class SQLiteRecordStage:
    def __init__(
        self,
        *,
        state: SQLiteState,
        workspace: Path,
        dataset: Mapping[str, Any],
        execution_id: str,
        job_id: str,
        schema_id: str,
        started_at: str,
        scheduled_for: str | None,
        store_raw_pages: bool,
        publish_records: bool = True,
    ) -> None:
        self.state = state
        self.workspace = workspace
        self.dataset = dataset
        self.dataset_id = str(dataset["datasetId"])
        self.dataset_dir = workspace / "datasets" / self.dataset_id
        self.execution_id = execution_id
        self.job_id = job_id
        self.schema_id = schema_id
        self.started_at = started_at
        self.scheduled_for = scheduled_for
        self.store_raw_pages = store_raw_pages
        self.publish_records = publish_records
        self.execution_dir = workspace / "executions" / execution_id
        self.rows_written = 0

    def _observe(
        self, db, identity: str, source_url: str, observed_at: str, row_key: str
    ) -> dict[str, Any] | None:
        existing = db.execute(
            "SELECT * FROM url_ledger WHERE dataset_id=? AND identity=?",
            (self.dataset_id, identity),
        ).fetchone()
        if existing is None:
            db.execute(
                """
                    INSERT INTO url_ledger(
                      dataset_id,identity,source_url,first_seen_at,last_seen_at,
                      first_execution_id,last_execution_id,seen_count,execution_count
                    ) VALUES(?,?,?,?,?,?,?,?,1)
                    """,
                (
                    self.dataset_id,
                    identity,
                    source_url,
                    observed_at,
                    observed_at,
                    self.execution_id,
                    self.execution_id,
                    1,
                ),
            )
            db.execute(
                "INSERT INTO url_observations VALUES(?,?,?)",
                (self.dataset_id, identity, self.execution_id),
            )
            db.execute(
                "INSERT INTO url_observation_rows VALUES(?,?,?,?)",
                (self.dataset_id, identity, self.execution_id, row_key),
            )
        else:
            observation = db.execute(
                """
                    INSERT OR IGNORE INTO url_observation_rows(
                      dataset_id,identity,execution_id,row_key
                    ) VALUES(?,?,?,?)
                    """,
                (self.dataset_id, identity, self.execution_id, row_key),
            )
            if observation.rowcount != 1:
                return None
            marker = db.execute(
                """
                    INSERT OR IGNORE INTO url_observations(dataset_id,identity,execution_id)
                    VALUES(?,?,?)
                    """,
                (self.dataset_id, identity, self.execution_id),
            )
            db.execute(
                """
                    UPDATE url_ledger SET source_url=?,
                      first_seen_at=min(first_seen_at,?),last_seen_at=max(last_seen_at,?),
                      last_execution_id=?,seen_count=seen_count+1,
                      execution_count=execution_count+?
                    WHERE dataset_id=? AND identity=?
                    """,
                (
                    source_url,
                    observed_at,
                    observed_at,
                    self.execution_id,
                    int(marker.rowcount == 1),
                    self.dataset_id,
                    identity,
                ),
            )
        row = db.execute(
            "SELECT * FROM url_ledger WHERE dataset_id=? AND identity=?",
            (self.dataset_id, identity),
        ).fetchone()
        return dict(row)

    async def emit(self, records: Sequence) -> None:
        if not self.publish_records:
            return
        mode = self.dataset.get("mode", "append_all")
        identity_field = self.dataset.get("identityColumn", "_source_url")
        with self.state.transaction() as db:
            for ordinal, record in enumerate(records):
                fields = dict(record.fields)
                source_url = record.source_url
                raw_identity = (
                    source_url
                    if identity_field == "_source_url"
                    else fields.get(identity_field)
                )
                identity = normalize_url_identity(raw_identity)
                observed_at = record.fetched_at.isoformat()
                key_input = json.dumps(
                    {
                        "execution": self.execution_id,
                        "source": source_url,
                        "template": record.template_id,
                        "ordinal": ordinal,
                    },
                    sort_keys=True,
                    default=str,
                    separators=(",", ":"),
                )
                row_key = hashlib.sha256(key_input.encode()).hexdigest()
                if (
                    db.execute(
                        "SELECT 1 FROM staged_records WHERE execution_id=? AND row_key=?",
                        (self.execution_id, row_key),
                    ).fetchone()
                    is not None
                ):
                    continue
                ledger = (
                    self._observe(db, identity, source_url, observed_at, row_key)
                    if identity
                    else None
                )
                if identity is not None and ledger is None:
                    continue  # idempotent retry of a suppressed or already staged row
                is_new = (
                    ledger is None or ledger["first_execution_id"] == self.execution_id
                )
                if mode == "new_urls_only" and identity is not None and not is_new:
                    continue
                row = {
                    **fields,
                    "_job_id": self.job_id,
                    "_execution_id": self.execution_id,
                    "_template_id": record.template_id,
                    "_template_origin": record.template_origin,
                    "_match_tier": record.match_tier,
                    "_schema_id": self.schema_id,
                    "_source_url": source_url,
                    "_crawled_at": observed_at,
                    "_execution_started_at": self.started_at,
                    "_scheduled_for": self.scheduled_for,
                    "_url_identity": identity,
                    "_is_new_url": is_new,
                    "_first_seen_at": ledger["first_seen_at"] if ledger else None,
                    "_last_seen_at": ledger["last_seen_at"] if ledger else None,
                    "_seen_count": ledger["seen_count"] if ledger else None,
                }
                inserted = db.execute(
                    "INSERT OR IGNORE INTO staged_records VALUES(?,?,?,?)",
                    (
                        self.execution_id,
                        row_key,
                        json.dumps(row, sort_keys=True, default=str),
                        datetime.now(timezone.utc).timestamp(),
                    ),
                )
                self.rows_written += int(inserted.rowcount == 1)

    def batches(self, batch_size=10_000):
        reader = sqlite3.connect(self.state.path)
        reader.row_factory = sqlite3.Row
        try:
            cursor = reader.execute(
                "SELECT row_json FROM staged_records WHERE execution_id=? ORDER BY row_key",
                (self.execution_id,),
            )
            while batch := cursor.fetchmany(batch_size):
                yield [json.loads(item["row_json"]) for item in batch]
        finally:
            reader.close()
