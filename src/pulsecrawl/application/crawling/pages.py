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
    PendingUrl,
    PageSnapshot,
    VisitedRow,
)
from pulsecrawl.application.templates.resolution import TemplateResolver
from pulsecrawl.application.crawling.records import RecordExtractor
from pulsecrawl.domain.crawling.urls import (
    host_of,
    in_scope,
    normalize_url,
    url_hash,
)


from pulsecrawl.domain.crawling.retry import retry_after_seconds


class CrawlPageProcessor:
    """Process one pending URL without owning the queue's execution loop."""

    def __init__(self, ports, admissions, dispatch):
        self._p, self._admissions, self._dispatch = ports, admissions, dispatch
        self._records = RecordExtractor(TemplateResolver())

    async def process(
        self, intent, item, stats, seed_hosts, extractors, system_extractors
    ):
        job_interval = 1.0 / intent.politeness.requests_per_second
        organization_interval = 1.0 / intent.politeness.organization_requests_per_second
        hashed = url_hash(item.url)
        if not await self._p.visited.admitted(intent.execution_id, hashed):
            # Compatibility with pending URL queues created before admissions were
            # persisted. Claim a budget slot before processing the item.
            if not await self._admissions._admit(intent, [item]):
                return
        if await self._p.visited.seen(intent.execution_id, hashed):
            return
        if item.depth > intent.scope.max_depth:
            await self._mark(intent, hashed, item, "skipped", "max depth exceeded")
            return

        if intent.politeness.respect_robots_txt:

            async def before_robots_fetch(robots_url: str) -> None:
                await self._dispatch._wait_until_reserved(
                    intent,
                    robots_url,
                    max(job_interval, organization_interval),
                    0.0,
                    stats,
                )

            decision = await self._p.robots.check(
                item.url,
                intent.politeness,
                before_fetch=before_robots_fetch,
            )
            stats.robots_checks += 1
            stats.robots_cache_hits += int(decision.cache_hit)
            stats.robots_fetches += int(decision.fetched)
            stats.robots_fetch_failures += int(
                decision.fetch_failed and decision.fetched
            )
            robots_delay = decision.crawl_delay
            if not decision.allowed:
                stats.robots_blocked += 1
                await self._mark(
                    intent, hashed, item, "robots_blocked", "blocked by robots.txt"
                )
                return
        else:
            robots_delay = None

        item = await self._dispatch.authorize_dispatch(
            intent, item, robots_delay, job_interval, organization_interval, stats
        )
        if item is None:
            return

        result = await self._p.fetcher.fetch(
            item.url, user_agent=intent.politeness.user_agent
        )
        stats.urls_attempted += 1

        if result.status in (429, 502, 503, 504) and item.retry_count < 3:
            if stats.urls_attempted < intent.scope.max_pages:
                delay = retry_after_seconds(
                    next(
                        (
                            value
                            for key, value in result.headers.items()
                            if key.lower() == "retry-after"
                        ),
                        None,
                    ),
                    item.retry_count,
                    self._p.clock.now(),
                )
                await self._p.pending_urls.push(
                    [
                        PendingUrl(
                            url=item.url,
                            depth=item.depth,
                            not_before=readiness_time(self._p.clock) + delay,
                            retry_count=item.retry_count + 1,
                        )
                    ]
                )
                stats.transient_retries += 1
                return

        if 300 <= result.status < 400:
            location = next(
                (
                    value
                    for key, value in result.headers.items()
                    if key.lower() == "location"
                ),
                None,
            )
            target = normalize_url(location or "", item.url)
            await self._mark(
                intent,
                hashed,
                item,
                "skipped",
                f"redirect to {target}"
                if target
                else "redirect without valid location",
            )
            if target and in_scope(
                target,
                seed_hosts=seed_hosts,
                same_domain_only=intent.scope.same_domain_only,
                include_patterns=intent.scope.include_patterns,
                exclude_patterns=intent.scope.exclude_patterns,
            ):
                redirected = await self._admissions._admit(
                    intent,
                    [PendingUrl(url=target, depth=item.depth)],
                )
                if redirected:
                    await self._p.pending_urls.push(
                        await self._admissions._schedule_admitted(
                            intent, redirected, stats
                        )
                    )
                    stats.pages_discovered += len(redirected)
            return

        if not result.ok:
            stats.pages_failed += 1
            await self._mark(
                intent, hashed, item, "failed", result.error or f"HTTP {result.status}"
            )
            return

        body = result.body or ""
        stats.pages_fetched += 1
        stats.bytes_processed += len(body.encode("utf-8", errors="replace"))

        if intent.store_raw_pages:
            await self._p.pages.save(
                hashed,
                PageSnapshot(
                    url=item.url,
                    final_url=result.final_url,
                    status=result.status,
                    headers=result.headers,
                    body=body,
                    depth=item.depth,
                    fetched_at=result.fetched_at,
                    body_truncated=result.body_truncated,
                    body_bytes=result.body_bytes,
                ),
            )

        source_url = normalize_url(result.final_url) or item.url
        records, match_tier = self._records.extract(
            intent,
            extractors,
            system_extractors,
            body,
            source_url,
            result.fetched_at,
        )
        self._record_template_coverage(stats, source_url, match_tier)
        if records:
            stats.records_extracted += len(records)
            await self._p.records.emit(records)

        discovered = await self._discover(
            intent, seed_hosts, body, item, source_url, stats
        )
        stats.pages_discovered += discovered
        # Completion is the output commit marker. Keep the durable visited
        # row queued until raw-page save, record emission, and discovery
        # have all succeeded; a hard crash then replays the URL instead of
        # silently losing its output. Record sinks must be idempotent.
        await self._mark(intent, hashed, item, "fetched", None)

    @staticmethod
    def _record_template_coverage(stats, source_url, match_tier) -> None:
        host = host_of(source_url)
        coverage = stats.template_coverage.setdefault(
            host,
            {
                "scopedMatches": 0,
                "stackFallbackMatches": 0,
                "systemFallbackMatches": 0,
                "unmatchedPages": 0,
                "needsTemplate": False,
                "sampleUrls": [],
            },
        )
        key = {
            "scoped": "scopedMatches",
            "stack_fallback": "stackFallbackMatches",
            "system_fallback": "systemFallbackMatches",
            None: "unmatchedPages",
        }[match_tier]
        coverage[key] += 1
        if match_tier in ("system_fallback", None):
            if (
                len(coverage["sampleUrls"]) < 5
                and source_url not in coverage["sampleUrls"]
            ):
                coverage["sampleUrls"].append(source_url)
        # This is a host-level authoring signal, not a claim that every page
        # on a covered site is an article. Discovery/index pages commonly use
        # system fallback; the host needs a template only when no authored
        # entry has matched anywhere in the execution.
        coverage["needsTemplate"] = (
            coverage["scopedMatches"] + coverage["stackFallbackMatches"] == 0
            and coverage["systemFallbackMatches"] + coverage["unmatchedPages"] > 0
        )

    async def _discover(
        self, intent, seed_hosts, body, item, source_url=None, stats=None
    ) -> int:
        if item.depth >= intent.scope.max_depth or self._admissions.remaining == 0:
            return 0
        fresh: list[PendingUrl] = []
        for link in self._p.links.extract_links(body, source_url or item.url):
            if not in_scope(
                link,
                seed_hosts=seed_hosts,
                same_domain_only=intent.scope.same_domain_only,
                include_patterns=intent.scope.include_patterns,
                exclude_patterns=intent.scope.exclude_patterns,
            ):
                continue
            fresh.append(PendingUrl(url=link, depth=item.depth + 1))
        admitted = await self._admissions._admit(intent, fresh)
        if admitted:
            await self._p.pending_urls.push(
                await self._admissions._schedule_admitted(intent, admitted, stats)
            )
        return len(admitted)

    async def _mark(self, intent, hashed, item, status, error) -> None:
        await self._p.visited.add(
            intent.execution_id,
            [
                VisitedRow(
                    url_hash=hashed,
                    url=item.url,
                    status=status,
                    depth=item.depth,
                    error=error,
                )
            ],
        )
