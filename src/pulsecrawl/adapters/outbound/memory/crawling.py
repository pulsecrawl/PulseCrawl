"""In-memory adapters: the local-mode defaults and the test doubles.

These define the reference semantics future distributed adapters (Redis,
Azure Tables) must match: see tests/test_conformance.py.
"""

from __future__ import annotations
from pulsecrawl.application.time import readiness_time

import asyncio
import heapq
import time
from datetime import datetime, timezone
from typing import Sequence

from pulsecrawl.domain.crawling.model import (
    FrontierUrl,
    PageSnapshot,
    Record,
    RobotsCacheEntry,
    VisitedRow,
)
from pulsecrawl.domain.crawling.politeness import (
    DEFAULT_DISPATCH_MARGIN_RATIO,
    guarded_interval_s,
)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()

    def readiness_time(self) -> float:
        return self.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class FakeClock:
    """Deterministic clock for tests: sleeping advances time instantly."""

    def __init__(self, start: float = 1000.0) -> None:
        self._monotonic = start
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return datetime.fromtimestamp(1_755_000_000 + self._monotonic, tz=timezone.utc)

    def monotonic(self) -> float:
        return self._monotonic

    def readiness_time(self) -> float:
        return self.monotonic()

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._monotonic += max(seconds, 0.0)
        # Yield to the event loop: a sleep that never awaits starves
        # concurrent tasks (background pollers busy-loop the process).
        await asyncio.sleep(0)

    def advance(self, seconds: float) -> None:
        self._monotonic += seconds


class MemoryRobotsCache:
    def __init__(self) -> None:
        self._entries: dict[str, RobotsCacheEntry] = {}

    async def get(self, origin: str) -> RobotsCacheEntry | None:
        return self._entries.get(origin)

    async def put(self, origin: str, entry: RobotsCacheEntry) -> None:
        self._entries[origin] = entry


class MemoryVisitedStore:
    def __init__(self) -> None:
        self._statuses: dict[str, dict[str, str]] = {}
        self.rows: dict[str, list[VisitedRow]] = {}

    async def admitted(self, execution_id: str, url_hash: str) -> bool:
        return url_hash in self._statuses.get(execution_id, {})

    async def seen(self, execution_id: str, url_hash: str) -> bool:
        status = self._statuses.get(execution_id, {}).get(url_hash)
        return status is not None and status != "queued"

    async def add(self, execution_id: str, rows: Sequence[VisitedRow]) -> None:
        statuses = self._statuses.setdefault(execution_id, {})
        stored = self.rows.setdefault(execution_id, [])
        for row in rows:
            statuses[row.url_hash] = row.status
            for index, existing in enumerate(stored):
                if existing.url_hash == row.url_hash:
                    stored[index] = row
                    break
            else:
                stored.append(row)

    def preload(self, execution_id: str, hashes: Sequence[str]) -> None:
        """Resume support: warm the set from a durable store's partition scan."""
        self._statuses.setdefault(execution_id, {}).update(
            {url_hash: "fetched" for url_hash in hashes}
        )


class MemoryHostGate:
    """Reference two-level organization and platform origin limiter.

    Granting consumes the slot; a deferral returns the wait WITHOUT moving
    the window, so bursts against a slow host cannot snowball its delay.
    """

    def __init__(
        self,
        clock,
        *,
        platform_requests_per_second: float = 5.0,
        dispatch_margin_ratio: float = DEFAULT_DISPATCH_MARGIN_RATIO,
    ) -> None:
        self._clock = clock
        self._platform_interval_s = 1.0 / platform_requests_per_second
        self._dispatch_margin_ratio = dispatch_margin_ratio
        guarded_interval_s(0.0, dispatch_margin_ratio)
        self._org_scheduled_next: dict[tuple[str, str], float] = {}
        self._global_scheduled_next: dict[str, float] = {}
        self._org_next_ok: dict[tuple[str, str], float] = {}
        self._global_next_ok: dict[str, float] = {}

    def _guard(self, interval_s: float) -> float:
        return guarded_interval_s(interval_s, self._dispatch_margin_ratio)

    async def schedule(
        self,
        org_id: str,
        origin: str,
        organization_interval_s: float,
        robots_interval_s: float,
    ) -> float:
        now = readiness_time(self._clock)
        org_key = (org_id, origin)
        slot = max(
            now,
            self._org_scheduled_next.get(org_key, 0.0),
            self._global_scheduled_next.get(origin, 0.0),
            self._org_next_ok.get(org_key, 0.0),
            self._global_next_ok.get(origin, 0.0),
        )
        self._org_scheduled_next[org_key] = slot + self._guard(organization_interval_s)
        self._global_scheduled_next[origin] = slot + self._guard(
            max(self._platform_interval_s, robots_interval_s)
        )
        return slot - now

    async def reserve(
        self,
        org_id: str,
        origin: str,
        organization_interval_s: float,
        robots_interval_s: float,
    ) -> float:
        now = readiness_time(self._clock)
        org_key = (org_id, origin)
        org_next = self._org_next_ok.get(org_key, 0.0)
        global_next = self._global_next_ok.get(origin, 0.0)
        wait = max(org_next - now, global_next - now, 0.0)
        if wait > 0:
            return wait
        self._org_next_ok[org_key] = now + self._guard(organization_interval_s)
        self._global_next_ok[origin] = now + self._guard(
            max(self._platform_interval_s, robots_interval_s)
        )
        return 0.0


class MemoryFrontier:
    """Min-heap on (not_before, insertion order)."""

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, FrontierUrl]] = []
        self._counter = 0

    async def push(self, items: Sequence[FrontierUrl]) -> None:
        for item in items:
            heapq.heappush(self._heap, (item.not_before, self._counter, item))
            self._counter += 1

    async def pop_ready(self, now: float) -> FrontierUrl | None:
        if self._heap and self._heap[0][0] <= now:
            return heapq.heappop(self._heap)[2]
        return None

    async def next_ready_at(self) -> float | None:
        return self._heap[0][0] if self._heap else None


class MemoryPageSink:
    def __init__(self) -> None:
        self.pages: dict[str, PageSnapshot] = {}

    async def save(self, url_hash: str, snapshot: PageSnapshot) -> None:
        self.pages[url_hash] = snapshot


class MemoryRecordSink:
    def __init__(self) -> None:
        self.records: list[Record] = []

    async def emit(self, records: Sequence[Record]) -> None:
        self.records.extend(records)
