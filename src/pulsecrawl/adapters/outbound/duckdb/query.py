"""Filesystem Parquet datasets, versioned manifests, and local URL history."""

from __future__ import annotations

import base64
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from pulsecrawl.domain.errors import (
    QueryTimeoutError,
)

_COMMENT_RE = re.compile(r"(--[^\n]*\n)|(/\*.*?\*/)", re.S)


def validate_select_only(sql: str) -> str:
    stripped = _COMMENT_RE.sub(" ", sql).strip().rstrip(";").strip()
    if not stripped:
        raise ValueError("empty query")
    if ";" in stripped:
        raise ValueError("only a single statement is allowed")
    if stripped.split(None, 1)[0].upper() not in ("SELECT", "WITH"):
        raise ValueError("only SELECT queries are allowed")
    return stripped


def _configure_duckdb(connection, paths: Sequence[Path]) -> None:
    """Apply resource limits before creating the allowlisted dataset view."""
    connection.execute("SET memory_limit='512MB'")
    connection.execute("SET threads=2")
    connection.execute("SET TimeZone='UTC'")
    # Use the same canonical path spelling that the table functions receive.
    # This matters on platforms such as macOS where /var resolves to
    # /private/var and older supported DuckDB releases compare allowlist
    # entries before normalizing both sides.
    connection.execute(
        "SET allowed_paths = ?", [[str(path.resolve()) for path in paths]]
    )


def _lock_down_duckdb(connection) -> None:
    """Disable any external access after the allowlisted view is created."""
    connection.execute("SET enable_external_access=false")
    connection.execute("SET autoinstall_known_extensions=false")
    connection.execute("SET autoload_known_extensions=false")


def _encode_cursor(offset: int) -> str:
    return (
        base64.urlsafe_b64encode(
            json.dumps({"v": 1, "offset": offset}, separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        offset = int(value["offset"])
        if value.get("v") != 1 or offset < 0:
            raise ValueError
        return offset
    except Exception as exc:
        raise ValueError("invalid cursor") from exc


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        import decimal

        if isinstance(value, decimal.Decimal):
            return float(value)
    except ImportError:  # pragma: no cover
        pass
    return str(value)


class DuckDBDatasetQuery:
    def __init__(self, files):
        self.files = files

    def query(
        self,
        sql: str,
        *,
        version: int | None = None,
        row_cap: int = 1_000,
        timeout_s: float = 30.0,
    ) -> dict[str, Any]:
        try:
            import duckdb
        except ImportError as missing:  # pragma: no cover
            raise ImportError(
                "workspace queries need DuckDB: pip install 'pulsecrawl[workspace]'"
            ) from missing
        statement = validate_select_only(sql)
        if isinstance(row_cap, bool) or not 1 <= row_cap <= 100_000:
            raise ValueError("row_cap must be between 1 and 100000")
        if not isinstance(timeout_s, (int, float)) or not 0 < timeout_s <= 300:
            raise ValueError("timeout_s must be between 0 and 300 seconds")
        paths = self.files.validate_files(version=version)
        if not paths:
            return {"columns": [], "rows": [], "truncated": False}
        escaped = ",".join("'" + str(path).replace("'", "''") + "'" for path in paths)
        connection = duckdb.connect(":memory:")
        expired = threading.Event()

        def interrupt() -> None:
            expired.set()
            connection.interrupt()

        timer = threading.Timer(float(timeout_s), interrupt)
        try:
            _configure_duckdb(connection, paths)
            _lock_down_duckdb(connection)
            connection.execute(
                "CREATE VIEW dataset AS SELECT * FROM read_parquet("
                f"[{escaped}], union_by_name=true, hive_partitioning=true)"
            )
            timer.start()
            try:
                cursor = connection.execute(
                    f"SELECT * FROM ({statement}) AS q LIMIT {int(row_cap) + 1}"
                )
            except Exception as exc:
                if expired.is_set():
                    raise QueryTimeoutError(
                        f"dataset query exceeded {float(timeout_s):g} seconds"
                    ) from exc
                raise
            columns = [item[0] for item in cursor.description]
            raw = cursor.fetchall()
        finally:
            timer.cancel()
            if timer.is_alive():
                timer.join(timeout=1)
            connection.close()
        return {
            "columns": columns,
            "rows": [[_jsonable(value) for value in row] for row in raw[:row_cap]],
            "truncated": len(raw) > row_cap,
        }

    def execution_urls(
        self,
        execution_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
        newness: str = "all",
        host: str | None = None,
        url_contains: str | None = None,
    ) -> dict[str, Any]:
        """Page the materialized URL rows from one execution.

        This intentionally reads the current manifest's Parquet set, matching
        the hosted endpoint.  In `new_urls_only` mode a later execution that
        only saw repeats therefore has no materialized URL rows.
        """
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if newness not in ("all", "new", "repeat"):
            raise ValueError("newness must be all, new, or repeat")
        offset = _decode_cursor(cursor)
        paths = self.files._paths()
        if not paths:
            return {"urls": [], "nextCursor": None}
        try:
            import duckdb
        except ImportError as missing:  # pragma: no cover
            raise ImportError(
                "workspace URL pages need DuckDB: pip install 'pulsecrawl[workspace]'"
            ) from missing
        escaped = ",".join("'" + str(path).replace("'", "''") + "'" for path in paths)
        connection = duckdb.connect(":memory:")
        try:
            _configure_duckdb(connection, paths)
            _lock_down_duckdb(connection)
            connection.execute(
                "CREATE VIEW dataset AS SELECT * FROM read_parquet("
                f"[{escaped}], union_by_name=true, hive_partitioning=true)"
            )
            columns = {
                row[0] for row in connection.execute("DESCRIBE dataset").fetchall()
            }
            if "_source_url" not in columns or "_execution_id" not in columns:
                return {"urls": [], "nextCursor": None}

            def column(name: str, fallback: str) -> str:
                return f'"{name}"' if name in columns else fallback

            identity = (
                f"coalesce(nullif(cast({column('_url_identity', 'NULL')} as varchar), ''), "
                "nullif(cast(\"_source_url\" as varchar), ''))"
            )
            is_new = (
                f"coalesce(try_cast({column('_is_new_url', 'NULL')} AS boolean), false)"
            )
            conditions = [
                'cast("_execution_id" as varchar)=?',
                f"{identity} is not null",
            ]
            params: list[object] = [execution_id]
            if newness == "new":
                conditions.append(f"{is_new}=true")
            elif newness == "repeat":
                conditions.append(f"{is_new}=false")
            if host:
                conditions.append(
                    'regexp_extract(lower(cast("_source_url" as varchar)), '
                    "'^https?://([^/:?#]+)', 1)=lower(?)"
                )
                params.append(host)
            if url_contains:
                conditions.append(
                    'strpos(lower(cast("_source_url" as varchar)), lower(?))>0'
                )
                params.append(url_contains)
            query = f"""
                SELECT
                  cast("_source_url" as varchar) AS url,
                  {identity} AS url_identity,
                  cast("_execution_id" as varchar) AS execution_id,
                  cast({column("_crawled_at", "NULL")} as varchar) AS crawled_at,
                  cast({column("_first_seen_at", "NULL")} as varchar) AS first_seen_at,
                  cast({column("_last_seen_at", "NULL")} as varchar) AS last_seen_at,
                  coalesce(try_cast({column("_seen_count", "NULL")} AS bigint), 1) AS seen_count,
                  {is_new} AS is_new
                FROM dataset
                WHERE {" AND ".join(conditions)}
                ORDER BY crawled_at DESC NULLS LAST, url_identity ASC, url ASC
                LIMIT ? OFFSET ?
            """
            params.extend([limit + 1, offset])
            result = connection.execute(query, params)
            names = [item[0] for item in result.description]
            raw = result.fetchall()
        finally:
            connection.close()
        has_more = len(raw) > limit
        urls = []
        for raw_row in raw[:limit]:
            row = dict(zip(names, raw_row))
            urls.append(
                {
                    "url": row["url"],
                    "urlIdentity": row["url_identity"],
                    "executionId": row["execution_id"],
                    "crawledAt": row["crawled_at"],
                    "firstSeenAt": row["first_seen_at"],
                    "lastSeenAt": row["last_seen_at"],
                    "seenCount": row["seen_count"],
                    "isNew": row["is_new"],
                }
            )
        return {
            "urls": urls,
            "nextCursor": _encode_cursor(offset + limit) if has_more else None,
        }
