"""The crawl engine: one execution, driven through ports.

Identical in local and hosted mode: only the adapters differ. The loop:

  pop ready URL → dedup → scope → robots → politeness gate → fetch →
  snapshot (optional) → extract → coerce → emit records → discover links

Politeness deferrals push the URL back with `not_before` and never advance
the host's window. When nothing is ready for longer than `park_threshold_s`
the engine returns `Parked` so the hosted worker can re-enqueue itself with
a visibility delay and scale to zero instead of sleeping on the clock.
"""

from __future__ import annotations
from pulsecrawl.application.time import readiness_time


from pulsecrawl.domain.crawling.model import (
    CrawlStats,
    ExecutionIntent,
    PendingUrl,
)
from pulsecrawl.domain.crawling.urls import (
    origin_of,
)


class CrawlDispatch:
    """Live HTTP dispatch guard; waiting never consumes another rate slot."""

    def __init__(self, ports, admissions, inline_wait_s):
        self._p, self._admissions = ports, admissions
        self._inline_wait_s = inline_wait_s

    async def _defer_to_pending_urls(
        self,
        item: PendingUrl,
        ready_at: float,
        stats: CrawlStats,
    ) -> None:
        delay = max(ready_at - readiness_time(self._p.clock), 0.0)
        stats.rate_limit_queue_deferrals += 1
        stats.rate_limit_queue_wait_seconds += delay
        await self._p.pending_urls.push(
            [
                PendingUrl(
                    url=item.url,
                    depth=item.depth,
                    not_before=ready_at,
                    rate_scheduled=True,
                    rate_slot_expires_at=item.rate_slot_expires_at,
                    rate_interval_s=item.rate_interval_s,
                    retry_count=item.retry_count,
                )
            ]
        )

    async def _reserve(
        self,
        intent: ExecutionIntent,
        url: str,
        organization_interval_s: float,
        robots_interval_s: float,
        stats: CrawlStats,
    ) -> float:
        wait = await self._p.gate.reserve(
            intent.org_id,
            origin_of(url),
            organization_interval_s,
            robots_interval_s,
        )
        if wait > 0:
            stats.rate_limit_deferrals += 1
            stats.rate_limit_wait_seconds += wait
        return wait

    async def _wait_until_reserved(
        self,
        intent: ExecutionIntent,
        url: str,
        organization_interval_s: float,
        robots_interval_s: float,
        stats: CrawlStats,
    ) -> None:
        """Gate robots network reads too; unlike pages they cannot be re-queued."""
        while True:
            wait = await self._p.gate.reserve(
                intent.org_id,
                origin_of(url),
                organization_interval_s,
                robots_interval_s,
            )
            if wait <= 0:
                return
            await self._p.clock.sleep(wait)

    async def authorize_dispatch(
        self, intent, item, robots_delay, job_interval, organization_interval, stats
    ):
        interval = max(job_interval, organization_interval, robots_delay or 0.0)
        scheduled_interval = interval

        if not item.rate_scheduled:
            scheduled, schedule_wait = await self._admissions._allocate_slot(
                intent,
                item,
                scheduled_interval,
                robots_delay or 0.0,
            )
            if schedule_wait > self._inline_wait_s:
                await self._defer_to_pending_urls(
                    scheduled,
                    readiness_time(self._p.clock) + schedule_wait,
                    stats,
                )
                return None
            if schedule_wait > 0:
                await self._p.clock.sleep(schedule_wait)
            item = scheduled

        # Queue visibility handles the normal admission time. The dispatch
        # lane is the final authority immediately before HTTP, protecting
        # against late slots becoming visible together and against another
        # job or organization using this origin. It intentionally ignores
        # the tail of future admission reservations.
        deferred = False
        while True:
            dispatch_wait = await self._reserve(
                intent,
                item.url,
                max(job_interval, organization_interval),
                robots_delay or 0.0,
                stats,
            )
            if dispatch_wait > self._inline_wait_s:
                await self._defer_to_pending_urls(
                    item,
                    readiness_time(self._p.clock) + dispatch_wait,
                    stats,
                )
                deferred = True
                break
            if dispatch_wait <= 0:
                break
            # A positive reserve result does not consume a gate slot.
            # Re-acquire after sleeping because another worker may claim
            # the same origin while we wait.
            await self._p.clock.sleep(dispatch_wait)
        if deferred:
            return None

        return item
