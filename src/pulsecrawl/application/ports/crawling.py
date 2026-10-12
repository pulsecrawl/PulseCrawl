"""Ports the engine depends on. Adapters: in-memory today, Redis/Azure later.

Semantics that adapters MUST preserve (encoded in tests/test_conformance.py):

- HostGate.schedule atomically allocates a future slot and returns its delay.
- HostGate.reserve returns 0 and consumes the live dispatch slot, or returns the seconds to
  wait WITHOUT consuming anything: a deferred caller must not push the
  window forward (otherwise bursty hosts snowball into ever-longer delays).
- Frontier orders by `not_before`, then FIFO; `pop_ready` never returns an
  item whose `not_before` is in the future.
- VisitedStore.seen answers for this execution only.
"""

from __future__ import annotations

from datetime import datetime
from typing import (
    Any,
    Awaitable,
    Callable,
    Mapping,
    Protocol,
    Sequence,
    runtime_checkable,
)

from pulsecrawl.domain.crawling.model import (
    FetchResult,
    FrontierUrl,
    PageSnapshot,
    Record,
    RobotsCacheEntry,
    VisitedRow,
)


@runtime_checkable
class Fetcher(Protocol):
    async def fetch(self, url: str, *, user_agent: str) -> FetchResult: ...


@runtime_checkable
class RobotsCache(Protocol):
    async def get(self, origin: str) -> RobotsCacheEntry | None:
        """Return the raw robots document and fetch metadata for one origin."""
        ...

    async def put(self, origin: str, entry: RobotsCacheEntry) -> None: ...


@runtime_checkable
class VisitedStore(Protocol):
    async def admitted(self, execution_id: str, url_hash: str) -> bool:
        """Whether this URL already owns one slot in the execution budget."""
        ...

    async def seen(self, execution_id: str, url_hash: str) -> bool: ...

    async def add(self, execution_id: str, rows: Sequence[VisitedRow]) -> None: ...


@runtime_checkable
class HostGate(Protocol):
    async def schedule(
        self,
        org_id: str,
        origin: str,
        organization_interval_s: float,
        robots_interval_s: float,
    ) -> float:
        """Allocate the next distributed org+origin/platform+origin slot.

        The positive return value is suitable for queue initial visibility.
        Unlike ``reserve``, the allocation is consumed even when it is in the
        future, so concurrent jobs receive distinct, ordered crawl times.
        """
        ...

    async def reserve(
        self,
        org_id: str,
        origin: str,
        organization_interval_s: float,
        robots_interval_s: float,
    ) -> float:
        """Atomically claim the live dispatch guard for an allocated slot.

        0.0 grants and consumes both slots. A positive wait consumes neither.
        The adapter adds its platform-wide interval and conservative dispatch
        margin to ``robots_interval_s``. The margin reduces arrival-compression
        risk but cannot control arbitrary network reordering.
        """
        ...


@runtime_checkable
class Frontier(Protocol):
    async def push(self, items: Sequence[FrontierUrl]) -> None: ...

    async def pop_ready(self, now: float) -> FrontierUrl | None: ...

    async def next_ready_at(self) -> float | None:
        """Earliest not_before among pending items, or None when empty."""
        ...


@runtime_checkable
class PageSink(Protocol):
    async def save(self, url_hash: str, snapshot: PageSnapshot) -> None: ...


@runtime_checkable
class RecordSink(Protocol):
    async def emit(self, records: Sequence[Record]) -> None:
        """Stage replay-safe records before the engine marks a page as fetched.

        Buffered implementations must let their lifecycle driver commit output
        before committing buffered visited state. Emit alone need not publish
        a dataset manifest. Do not assume exactly-once HTTP delivery.
        """
        ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class ExtractorRegistry(Protocol):
    def get_engine(self, name: str) -> Callable[[str, Mapping], list[dict[str, Any]]]:
        """Return a callable (body, mappings) -> raw records."""
        ...


class LinkParser(Protocol):
    def extract_links(self, html: str, base_url: str) -> list[str]: ...


class RobotsPolicy(Protocol):
    async def check(
        self,
        url: str,
        politeness,
        *,
        before_fetch: Callable[[str], Awaitable[None]] | None = None,
    ): ...
