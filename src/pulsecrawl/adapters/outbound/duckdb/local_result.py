"""Bounded SQL over an ephemeral result or legacy JSONL execution dataset."""

from __future__ import annotations
import os
import threading
from pathlib import Path


class LocalResultQuery:
    def __init__(self, result):
        self.records, self.execution_dir, self.dataset_path = (
            result.records,
            result.execution_dir,
            result.dataset_path,
        )

    def query(
        self,
        query: str,
        *,
        row_cap: int = 10_000,
        timeout_s: float = 30.0,
    ):
        """Run SQL over this crawl's records (table name: `records`).

        Requires the optional extra:  pip install pulsecrawl[sql]
        Returns a list of dicts (one per row).
        """
        try:
            import duckdb
        except ImportError as missing:  # pragma: no cover: import guard
            raise ImportError(
                "SQL support needs DuckDB: pip install 'pulsecrawl[sql]'"
            ) from missing
        import json as _json
        import tempfile

        from pulsecrawl.domain.errors import QueryTimeoutError
        from pulsecrawl.adapters.outbound.duckdb.query import (
            _configure_duckdb,
            _lock_down_duckdb,
            validate_select_only,
        )

        statement = validate_select_only(query)
        if isinstance(row_cap, bool) or not 1 <= row_cap <= 100_000:
            raise ValueError("row_cap must be between 1 and 100000")
        if not isinstance(timeout_s, (int, float)) or not 0 < timeout_s <= 300:
            raise ValueError("timeout_s must be between 0 and 300 seconds")

        connection = duckdb.connect(":memory:")
        temporary_path: Path | None = None
        expired = threading.Event()

        def interrupt() -> None:
            expired.set()
            connection.interrupt()

        timer = threading.Timer(float(timeout_s), interrupt)
        try:
            if self.execution_dir is not None:
                paths = sorted(
                    Path(self.dataset_path).glob("executions/*/records-*.jsonl")
                )
            elif self.records:
                handle = tempfile.NamedTemporaryFile(
                    "w", suffix=".jsonl", delete=False, encoding="utf-8"
                )
                with handle:
                    for record in self.records:
                        handle.write(_json.dumps(record) + "\n")
                temporary_path = Path(handle.name)
                paths = [temporary_path]
            else:
                paths = []
            _configure_duckdb(connection, paths)
            if paths:
                sources = ",".join(
                    "'" + str(path.resolve()).replace("'", "''") + "'" for path in paths
                )
                connection.execute(
                    f"CREATE VIEW records AS SELECT * FROM read_json_auto([{sources}])"
                )
            else:
                connection.execute("CREATE VIEW records AS SELECT 1 WHERE false")
            _lock_down_duckdb(connection)
            timer.start()
            try:
                cursor = connection.execute(
                    f"SELECT * FROM ({statement}) AS q LIMIT {int(row_cap) + 1}"
                )
            except Exception as exc:
                if expired.is_set():
                    raise QueryTimeoutError(
                        f"local SQL query exceeded {float(timeout_s):g} seconds"
                    ) from exc
                raise
            columns = [d[0] for d in cursor.description]
            rows = cursor.fetchall()
            if len(rows) > row_cap:
                raise ValueError(f"query result exceeds row_cap={row_cap}")
            return [dict(zip(columns, row)) for row in rows]
        finally:
            timer.cancel()
            if timer.is_alive():
                timer.join(timeout=1)
            connection.close()
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass
