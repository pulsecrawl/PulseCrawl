"""Robots.txt retrieval, caching, and per-URL decisions.

The raw document is cached per normalized origin and evaluated for every URL
and user agent. 4xx responses mean the robots file is unavailable and permit
access; network errors, 429, and 5xx fail closed so an outage cannot silently
turn into an unrestricted crawl.
"""

from __future__ import annotations
from pulsecrawl.application.time import readiness_time

from dataclasses import dataclass
from typing import Awaitable, Callable
import urllib.robotparser

from pulsecrawl.domain.crawling.model import Politeness, RobotsCacheEntry
from pulsecrawl.application.ports.crawling import Clock, Fetcher, RobotsCache
from pulsecrawl.domain.crawling.urls import normalize_url, origin_of

DEFAULT_TTL_S = 3600.0
FAIL_CLOSED_TEXT = "User-agent: *\nDisallow: /\n"


@dataclass(frozen=True)
class RobotsDecision:
    allowed: bool
    crawl_delay: float | None
    cache_hit: bool
    fetched: bool
    fetch_failed: bool

    def __iter__(self):
        """Retain the historical ``allowed, delay = check(...)`` convenience."""
        yield self.allowed
        yield self.crawl_delay


BeforeFetch = Callable[[str], Awaitable[None]]


class RobotsService:
    def __init__(
        self,
        fetcher: Fetcher,
        cache: RobotsCache,
        clock: Clock,
        *,
        ttl_s: float = DEFAULT_TTL_S,
    ) -> None:
        self._fetcher = fetcher
        self._cache = cache
        self._clock = clock
        self._ttl_s = ttl_s

    async def check(
        self,
        url: str,
        politeness: Politeness,
        *,
        before_fetch: BeforeFetch | None = None,
    ) -> RobotsDecision:
        """Evaluate one URL and report enough metadata for cheap monitoring."""
        origin = origin_of(url)
        entry, cache_hit, fetched = await self._entry_for(
            origin, politeness.user_agent, before_fetch
        )
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(entry.text.splitlines())
        delay = parser.crawl_delay(politeness.user_agent)
        return RobotsDecision(
            allowed=parser.can_fetch(politeness.user_agent, url),
            crawl_delay=float(delay) if delay is not None else None,
            cache_hit=cache_hit,
            fetched=fetched,
            fetch_failed=entry.fetch_failed,
        )

    async def _entry_for(
        self,
        origin: str,
        user_agent: str,
        before_fetch: BeforeFetch | None,
    ) -> tuple[RobotsCacheEntry, bool, bool]:
        cached = await self._cache.get(origin)
        if (
            cached is not None
            and readiness_time(self._clock) - cached.fetched_at < self._ttl_s
        ):
            return cached, True, False

        robots_url = f"{origin}/robots.txt"
        result = None
        for _redirect in range(6):
            if before_fetch is not None:
                await before_fetch(robots_url)
            result = await self._fetcher.fetch(robots_url, user_agent=user_agent)
            if not 300 <= result.status < 400:
                break
            location = next(
                (
                    value
                    for key, value in result.headers.items()
                    if key.lower() == "location"
                ),
                None,
            )
            target = normalize_url(location or "", robots_url)
            if target is None:
                break
            robots_url = target
        assert result is not None
        # RFC 9309 unavailable (4xx other than throttling): crawlers may access.
        if result.status in range(400, 500) and result.status != 429:
            entry = RobotsCacheEntry(
                "", readiness_time(self._clock), fetch_failed=False
            )
        elif result.ok:
            entry = RobotsCacheEntry(result.body or "", readiness_time(self._clock))
        else:
            entry = RobotsCacheEntry(
                FAIL_CLOSED_TEXT, readiness_time(self._clock), fetch_failed=True
            )
        await self._cache.put(origin, entry)
        return entry, False, True
