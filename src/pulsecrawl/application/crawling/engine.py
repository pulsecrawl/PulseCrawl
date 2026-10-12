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

from dataclasses import dataclass

from pulsecrawl.domain.crawling.model import (
    Completed,
    CrawlOutcome,
    ExecutionIntent,
    Parked,
)
from pulsecrawl.application.ports.crawling import (
    Clock,
    Fetcher,
    Frontier,
    HostGate,
    PageSink,
    RecordSink,
    VisitedStore,
)
from pulsecrawl.domain.templates.selection import TemplateSelection
from pulsecrawl.application.templates.resolution import TemplateResolver
from pulsecrawl.application.ports.crawling import (
    ExtractorRegistry,
    LinkParser,
    RobotsPolicy,
)
from pulsecrawl.domain.crawling.urls import (
    host_of,
    normalize_url,
)


from pulsecrawl.application.crawling.admission import FrontierAdmissions
from pulsecrawl.application.crawling.dispatch import CrawlDispatch
from pulsecrawl.application.crawling.pages import CrawlPageProcessor


@dataclass
class EnginePorts:
    fetcher: Fetcher
    robots: RobotsPolicy
    visited: VisitedStore
    gate: HostGate
    frontier: Frontier
    pages: PageSink
    records: RecordSink
    clock: Clock
    extractors: ExtractorRegistry
    links: LinkParser


class CrawlEngine:
    """Application runner shared by ephemeral, durable local and hosted adapters."""

    def __init__(
        self,
        ports,
        *,
        park_threshold_s=60.0,
        inline_wait_s=5.0,
        queue_visibility_resolution_s=0.0,
        should_stop=None,
        admission_remaining=None,
    ):
        self._p, self._park_threshold_s = ports, park_threshold_s
        self._should_stop = should_stop or (lambda: False)
        self._admissions = FrontierAdmissions(
            ports,
            remaining=admission_remaining,
            inline_wait_s=inline_wait_s,
            visibility_resolution_s=max(queue_visibility_resolution_s, 0.0),
        )
        self._dispatch = CrawlDispatch(ports, self._admissions, inline_wait_s)
        self._pages = CrawlPageProcessor(ports, self._admissions, self._dispatch)

    async def seed(self, intent):
        return await self._admissions.seed(intent)

    _applicable_templates = staticmethod(TemplateSelection.applicable)
    _apply_template_stack = staticmethod(TemplateResolver.apply_stack)

    async def run(self, intent: ExecutionIntent) -> CrawlOutcome:
        stats = self._admissions.initial_stats()
        seed_hosts = frozenset(host_of(s) for s in intent.seeds if normalize_url(s))
        extractors = [
            (t, self._p.extractors.get_engine(t.engine)) for t in intent.templates
        ]
        system_extractors = [
            (t, self._p.extractors.get_engine(t.engine))
            for t in intent.system_templates
        ]

        while stats.urls_attempted < intent.scope.max_pages and not self._should_stop():
            now = readiness_time(self._p.clock)
            item = await self._p.frontier.pop_ready(now)

            if item is None:
                next_ready = await self._p.frontier.next_ready_at()
                if next_ready is None:
                    break  # frontier drained: done
                wait = max(next_ready - now, 0.0)
                if wait > self._park_threshold_s:
                    return Parked(stats=stats, resume_after_s=wait)
                await self._p.clock.sleep(wait)
                continue

            await self._pages.process(
                intent, item, stats, seed_hosts, extractors, system_extractors
            )

        return Completed(stats=stats)
