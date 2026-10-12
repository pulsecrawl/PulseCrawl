"""Filesystem Parquet datasets, versioned manifests, and local URL history."""

from __future__ import annotations

from typing import Any


from pulsecrawl.adapters.outbound.duckdb.query import _encode_cursor, _decode_cursor


class SQLiteURLHistory:
    def __init__(self, state, dataset_id):
        self.state, self.dataset_id = state, dataset_id

    def urls(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
        newness: str = "all",
        host: str | None = None,
        url_contains: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if newness not in ("all", "new", "repeat"):
            raise ValueError("newness must be all, new, or repeat")
        offset = _decode_cursor(cursor)
        filters = ["dataset_id=?"]
        params: list[object] = [self.dataset_id]
        if newness == "new":
            filters.append("execution_count=1")
        elif newness == "repeat":
            filters.append("execution_count>1")
        if host:
            filters.append("lower(source_url) LIKE ?")
            params.append(f"%://{host.lower()}/%")
        if url_contains:
            filters.append("instr(lower(source_url),lower(?))>0")
            params.append(url_contains)
        params.extend([limit + 1, offset])
        rows = self.state.execute(
            f"""
            SELECT * FROM url_ledger WHERE {" AND ".join(filters)}
            ORDER BY last_seen_at DESC,identity ASC LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        has_more = len(rows) > limit
        values = [
            {
                "url": row["source_url"],
                "urlIdentity": row["identity"],
                "firstSeenAt": row["first_seen_at"],
                "lastSeenAt": row["last_seen_at"],
                "seenCount": row["seen_count"],
                "executionCount": row["execution_count"],
                "isNew": row["execution_count"] == 1,
                "firstExecutionId": row["first_execution_id"],
                "lastExecutionId": row["last_execution_id"],
            }
            for row in rows[:limit]
        ]
        return {
            "urls": values,
            "nextCursor": _encode_cursor(offset + limit) if has_more else None,
        }
