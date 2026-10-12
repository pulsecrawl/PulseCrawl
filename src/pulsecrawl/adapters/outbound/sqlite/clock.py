"""Durable, single-machine adapters for an open-source PulseCrawl workspace.

SQLite is authoritative for operational state.  Python dictionaries may cache
reads, but a process restart must never lose a frontier item, URL admission,
schedule, rate-limit clock, or dataset identity observation.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone


class EpochClock:
    """Wall-clock seconds make persisted ``not_before`` values restart-safe."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        """Legacy readiness coordinate; use elapsed_time for duration measurements."""
        return time.time()

    def readiness_time(self) -> float:
        return time.time()

    def elapsed_time(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(seconds, 0.0))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
