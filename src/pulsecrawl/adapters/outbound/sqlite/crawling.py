"""Durable, single-machine adapters for an open-source PulseCrawl workspace.

SQLite is authoritative for operational state.  Python dictionaries may cache
reads, but a process restart must never lose a pending URL, URL admission,
schedule, rate-limit clock, or dataset identity observation.
"""

from __future__ import annotations

import time
from typing import Sequence

from pulsecrawl.domain.crawling.model import PendingUrl, RobotsCacheEntry, VisitedRow
from pulsecrawl.domain.crawling.politeness import (
    DEFAULT_DISPATCH_MARGIN_RATIO,
    guarded_interval_s,
)
from pulsecrawl.domain.crawling.urls import url_hash


from pulsecrawl.adapters.outbound.sqlite.state import SQLiteState
from pulsecrawl.adapters.outbound.sqlite.clock import EpochClock


class SQLiteVisitedStore:
    def __init__(self, state: SQLiteState) -> None:
        self.state = state

    async def admitted(self, execution_id: str, hashed: str) -> bool:
        return (
            self.state.execute(
                "SELECT 1 FROM visited WHERE execution_id=? AND url_hash=?",
                (execution_id, hashed),
            ).fetchone()
            is not None
        )

    async def seen(self, execution_id: str, hashed: str) -> bool:
        row = self.state.execute(
            "SELECT status FROM visited WHERE execution_id=? AND url_hash=?",
            (execution_id, hashed),
        ).fetchone()
        return row is not None and row["status"] != "queued"

    async def add(self, execution_id: str, rows: Sequence[VisitedRow]) -> None:
        now = time.time()
        with self.state.transaction() as db:
            for row in rows:
                db.execute(
                    """
                    INSERT INTO visited(execution_id,url_hash,url,status,depth,error,updated_at)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(execution_id,url_hash) DO UPDATE SET
                      url=excluded.url,status=excluded.status,depth=excluded.depth,
                      error=excluded.error,updated_at=excluded.updated_at
                    """,
                    (
                        execution_id,
                        row.url_hash,
                        row.url,
                        row.status,
                        row.depth,
                        row.error,
                        now,
                    ),
                )
                if row.status != "queued":
                    db.execute(
                        "DELETE FROM pending_urls WHERE execution_id=? AND url_hash=?",
                        (execution_id, row.url_hash),
                    )

    def admitted_count(self, execution_id: str) -> int:
        row = self.state.execute(
            "SELECT count(*) AS n FROM visited WHERE execution_id=?", (execution_id,)
        ).fetchone()
        return int(row["n"])


class SQLitePendingUrls:
    def __init__(
        self,
        state: SQLiteState,
        execution_id: str,
        *,
        lease_seconds: float = 300.0,
    ) -> None:
        self.state = state
        self.execution_id = execution_id
        self.lease_seconds = lease_seconds

    async def push(self, items: Sequence[PendingUrl]) -> None:
        with self.state.transaction() as db:
            for item in items:
                hashed = url_hash(item.url)
                db.execute(
                    """
                    INSERT INTO pending_urls(
                      execution_id,url_hash,url,depth,not_before,rate_scheduled,
                      rate_slot_expires_at,rate_interval_s,retry_count,state,lease_until
                    ) VALUES(?,?,?,?,?,?,?,?,?, 'pending',NULL)
                    ON CONFLICT(execution_id,url_hash) DO UPDATE SET
                      url=excluded.url,depth=excluded.depth,
                      not_before=excluded.not_before,
                      rate_scheduled=excluded.rate_scheduled,
                      rate_slot_expires_at=excluded.rate_slot_expires_at,
                      rate_interval_s=excluded.rate_interval_s,
                      retry_count=excluded.retry_count,
                      state='pending',lease_until=NULL
                    """,
                    (
                        self.execution_id,
                        hashed,
                        item.url,
                        item.depth,
                        item.not_before,
                        int(item.rate_scheduled),
                        item.rate_slot_expires_at,
                        item.rate_interval_s,
                        item.retry_count,
                    ),
                )

    async def pop_ready(self, now: float) -> PendingUrl | None:
        with self.state.transaction() as db:
            row = db.execute(
                """
                SELECT * FROM pending_urls
                WHERE execution_id=?
                  AND ((state='pending' AND not_before<=?)
                    OR (state='leased' AND lease_until<=?))
                ORDER BY CASE WHEN state='leased' THEN lease_until ELSE not_before END,
                         sequence
                LIMIT 1
                """,
                (self.execution_id, now, now),
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE pending_urls SET state='leased',lease_until=? WHERE sequence=?",
                (now + self.lease_seconds, row["sequence"]),
            )
        return PendingUrl(
            url=row["url"],
            depth=int(row["depth"]),
            not_before=float(row["not_before"]),
            rate_scheduled=bool(row["rate_scheduled"]),
            rate_slot_expires_at=float(row["rate_slot_expires_at"]),
            rate_interval_s=float(row["rate_interval_s"]),
            retry_count=int(row["retry_count"]),
        )

    async def next_ready_at(self) -> float | None:
        row = self.state.execute(
            """
            SELECT min(CASE WHEN state='leased' THEN lease_until ELSE not_before END) AS ready
            FROM pending_urls WHERE execution_id=?
            """,
            (self.execution_id,),
        ).fetchone()
        return None if row is None or row["ready"] is None else float(row["ready"])

    def pending_count(self) -> int:
        row = self.state.execute(
            "SELECT count(*) AS n FROM pending_urls WHERE execution_id=?",
            (self.execution_id,),
        ).fetchone()
        return int(row["n"])


class SQLiteRobotsCache:
    def __init__(self, state: SQLiteState) -> None:
        self.state = state
        self._memory: dict[str, RobotsCacheEntry] = {}

    async def get(self, origin: str) -> RobotsCacheEntry | None:
        cached = self._memory.get(origin)
        if cached is not None:
            return cached
        row = self.state.execute(
            "SELECT text,fetched_at,fetch_failed FROM robots_cache WHERE origin=?",
            (origin,),
        ).fetchone()
        if row is None:
            return None
        entry = RobotsCacheEntry(
            text=row["text"],
            fetched_at=float(row["fetched_at"]),
            fetch_failed=bool(row["fetch_failed"]),
        )
        self._memory[origin] = entry
        return entry

    async def put(self, origin: str, entry: RobotsCacheEntry) -> None:
        self._memory[origin] = entry
        self.state.execute(
            """
            INSERT INTO robots_cache(origin,text,fetched_at,fetch_failed) VALUES(?,?,?,?)
            ON CONFLICT(origin) DO UPDATE SET text=excluded.text,
              fetched_at=excluded.fetched_at,fetch_failed=excluded.fetch_failed
            """,
            (origin, entry.text, entry.fetched_at, int(entry.fetch_failed)),
        )


class SQLiteHostGate:
    """Workspace-wide organization/site limiter shared by every local job."""

    def __init__(
        self,
        state: SQLiteState,
        clock: EpochClock,
        *,
        platform_requests_per_second: float = 5.0,
        dispatch_margin_ratio: float = DEFAULT_DISPATCH_MARGIN_RATIO,
    ) -> None:
        self.state = state
        self.clock = clock
        self.platform_interval_s = 1.0 / platform_requests_per_second
        self.dispatch_margin_ratio = dispatch_margin_ratio
        guarded_interval_s(0.0, dispatch_margin_ratio)

    def _guard(self, interval_s: float) -> float:
        return guarded_interval_s(interval_s, self.dispatch_margin_ratio)

    @staticmethod
    def _next(db, lane: str, org_id: str, origin: str) -> float:
        row = db.execute(
            "SELECT next_at FROM gate_clocks WHERE lane=? AND org_id=? AND origin=?",
            (lane, org_id, origin),
        ).fetchone()
        return 0.0 if row is None else float(row["next_at"])

    @staticmethod
    def _set(db, lane: str, org_id: str, origin: str, value: float) -> None:
        db.execute(
            """
            INSERT INTO gate_clocks(lane,org_id,origin,next_at) VALUES(?,?,?,?)
            ON CONFLICT(lane,org_id,origin) DO UPDATE SET next_at=excluded.next_at
            """,
            (lane, org_id, origin, value),
        )

    async def schedule(
        self,
        org_id: str,
        origin: str,
        organization_interval_s: float,
        robots_interval_s: float,
    ) -> float:
        now = self.clock.monotonic()
        with self.state.transaction() as db:
            slot = max(
                now,
                self._next(db, "scheduled-org", org_id, origin),
                self._next(db, "scheduled-global", "*", origin),
                self._next(db, "live-org", org_id, origin),
                self._next(db, "live-global", "*", origin),
            )
            self._set(
                db,
                "scheduled-org",
                org_id,
                origin,
                slot + self._guard(organization_interval_s),
            )
            self._set(
                db,
                "scheduled-global",
                "*",
                origin,
                slot + self._guard(max(self.platform_interval_s, robots_interval_s)),
            )
        return max(slot - now, 0.0)

    async def reserve(
        self,
        org_id: str,
        origin: str,
        organization_interval_s: float,
        robots_interval_s: float,
    ) -> float:
        now = self.clock.monotonic()
        with self.state.transaction() as db:
            org_next = self._next(db, "live-org", org_id, origin)
            global_next = self._next(db, "live-global", "*", origin)
            wait = max(org_next - now, global_next - now, 0.0)
            if wait > 0:
                return wait
            self._set(
                db,
                "live-org",
                org_id,
                origin,
                now + self._guard(organization_interval_s),
            )
            self._set(
                db,
                "live-global",
                "*",
                origin,
                now + self._guard(max(self.platform_interval_s, robots_interval_s)),
            )
        return 0.0
