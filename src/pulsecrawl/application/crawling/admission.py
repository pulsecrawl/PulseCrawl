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
    VisitedRow,
)
from pulsecrawl.domain.crawling.urls import (
    normalize_url,
    origin_of,
    url_hash,
)


class PendingUrlAdmissions:
    """Own one execution's unique URL admission budget and future rate slots."""

    def __init__(self, ports, *, remaining, inline_wait_s, visibility_resolution_s):
        self._p, self._admission_remaining = ports, remaining
        self._inline_wait_s, self._queue_visibility_resolution_s = (
            inline_wait_s,
            visibility_resolution_s,
        )
        self._admitted_this_run = set()
        self._pending_queue_deferrals = 0
        self._pending_queue_wait_seconds = 0.0

    @property
    def remaining(self):
        return self._admission_remaining

    def initial_stats(self):
        stats = CrawlStats(
            rate_limit_queue_deferrals=self._pending_queue_deferrals,
            rate_limit_queue_wait_seconds=self._pending_queue_wait_seconds,
        )
        self._pending_queue_deferrals, self._pending_queue_wait_seconds = 0, 0.0
        return stats

    async def seed(self, intent: ExecutionIntent) -> int:
        """Enqueue seed URLs. Call once per execution, not on resume."""
        items = []
        for seed in intent.seeds:
            normalized = normalize_url(seed)
            if normalized:
                items.append(PendingUrl(url=normalized, depth=0))
        admitted = await self._admit(intent, items)
        if admitted:
            scheduled = await self._schedule_admitted(intent, admitted)
            await self._p.pending_urls.push(scheduled)
        return len(admitted)

    async def _allocate_slot(
        self,
        intent: ExecutionIntent,
        item: PendingUrl,
        scheduled_interval: float,
        robots_interval: float,
    ) -> tuple[PendingUrl, float]:
        wait = await self._p.gate.schedule(
            intent.org_id,
            origin_of(item.url),
            scheduled_interval,
            robots_interval,
        )
        now_mono = readiness_time(self._p.clock)
        return (
            PendingUrl(
                url=item.url,
                depth=item.depth,
                not_before=now_mono + wait,
                rate_scheduled=True,
                rate_slot_expires_at=(
                    self._p.clock.now().timestamp()
                    + wait
                    + max(
                        self._queue_visibility_resolution_s,
                        self._inline_wait_s,
                        0.001,
                    )
                ),
                rate_interval_s=scheduled_interval,
                retry_count=item.retry_count,
            ),
            wait,
        )

    async def _schedule_admitted(
        self,
        intent: ExecutionIntent,
        items: list[PendingUrl],
        stats: CrawlStats | None = None,
    ) -> list[PendingUrl]:
        interval = max(
            1.0 / intent.politeness.requests_per_second,
            1.0 / intent.politeness.organization_requests_per_second,
        )
        scheduled: list[PendingUrl] = []
        for item in items:
            allocated, wait = await self._allocate_slot(intent, item, interval, 0.0)
            scheduled.append(allocated)
            if wait > 0:
                if stats is None:
                    self._pending_queue_deferrals += 1
                    self._pending_queue_wait_seconds += wait
                else:
                    stats.rate_limit_queue_deferrals += 1
                    stats.rate_limit_queue_wait_seconds += wait
        return scheduled

    async def _admit(
        self, intent: ExecutionIntent, items: list[PendingUrl]
    ) -> list[PendingUrl]:
        """Reserve unique Pending URLs slots before enqueueing them.

        The queued marker is durable in hosted mode, so resumes subtract both
        processed and pending URLs from the same execution budget.
        """
        if self._admission_remaining is None:
            self._admission_remaining = intent.scope.max_pages
        admitted: list[PendingUrl] = []
        rows: list[VisitedRow] = []
        for item in items:
            if self._admission_remaining <= 0:
                break
            hashed = url_hash(item.url)
            if hashed in self._admitted_this_run:
                continue
            if await self._p.visited.admitted(intent.execution_id, hashed):
                continue
            self._admitted_this_run.add(hashed)
            self._admission_remaining -= 1
            admitted.append(item)
            rows.append(
                VisitedRow(
                    url_hash=hashed,
                    url=item.url,
                    status="queued",
                    depth=item.depth,
                )
            )
        if rows:
            await self._p.visited.add(intent.execution_id, rows)
        return admitted
