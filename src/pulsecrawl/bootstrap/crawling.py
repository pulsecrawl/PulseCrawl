"""Crawl dependency wiring and ownership of local transport resources."""

from contextlib import AsyncExitStack, asynccontextmanager
from types import SimpleNamespace

from pulsecrawl.application.crawling.engine import CrawlEngine, EnginePorts
from pulsecrawl.application.crawling.robots import RobotsService
from pulsecrawl.adapters.outbound.http.fetcher import AiohttpFetcher
from pulsecrawl.adapters.outbound.html.extraction import HtmlExtractorRegistry
from pulsecrawl.adapters.outbound.html.links import HtmlLinkParser


@asynccontextmanager
async def fetch_resources(*, fetcher=None, allow_private_networks=False):
    """Close only transports constructed here, including partial setup failures."""
    async with AsyncExitStack() as resources:
        if fetcher is not None:
            yield fetcher, fetcher
            return
        http = AiohttpFetcher(
            allow_redirects=False, allow_private_networks=allow_private_networks
        )
        resources.push_async_callback(http.close)
        robots = AiohttpFetcher(
            accepted_content_types=None,
            max_body_bytes=512 * 1024,
            allow_redirects=False,
            allow_private_networks=allow_private_networks,
        )
        resources.push_async_callback(robots.close)
        yield http, robots


def engine_ports(**kwargs):
    """Standard HTML strategies; callers supply persistence and timing adapters."""
    return EnginePorts(
        extractors=HtmlExtractorRegistry(), links=HtmlLinkParser(), **kwargs
    )


class LocalExecutionRuntimeFactory:
    def __init__(self, *, state, root, datasets, org_id):
        self.state, self.root, self.datasets, self.org_id = (
            state,
            root,
            datasets,
            org_id,
        )

    @asynccontextmanager
    async def open(
        self,
        execution,
        started,
        *,
        fetcher=None,
        allow_private_networks=False,
        should_stop=None,
    ):
        # Hosted and ephemeral callers reuse engine_ports/fetch_resources
        # without importing any local persistence implementation.
        from pulsecrawl.adapters.outbound.sqlite.clock import EpochClock
        from pulsecrawl.adapters.outbound.sqlite.crawling import (
            SQLiteVisitedStore,
            SQLiteFrontier,
            SQLiteRobotsCache,
            SQLiteHostGate,
        )
        from pulsecrawl.adapters.inbound.python.intent import IntentMapper
        from pulsecrawl.domain.crawling.model import FrontierUrl
        from pulsecrawl.bootstrap.datasets import LocalDatasetWriter

        execution_id = execution["executionId"]
        intent = IntentMapper.from_message_intent(
            execution_id=execution_id,
            org_id=self.org_id,
            job_id=execution["jobId"],
            intent=execution["intent"],
        )
        writer = LocalDatasetWriter(
            state=self.state,
            workspace=self.root,
            dataset=self.datasets.get(execution["datasetId"]),
            execution_id=execution_id,
            job_id=execution["jobId"],
            schema_id=intent.schema.schema_id,
            started_at=started,
            scheduled_for=execution["scheduledFor"],
            store_raw_pages=intent.store_raw_pages,
            publish_records=bool(execution["intent"].get("publishRecords", True)),
        )
        clock = EpochClock()
        visited, frontier = (
            SQLiteVisitedStore(self.state),
            SQLiteFrontier(self.state, execution_id),
        )
        admitted = visited.admitted_count(execution_id)
        async with fetch_resources(
            fetcher=fetcher, allow_private_networks=allow_private_networks
        ) as (http, robots_http):
            # Reconcile admission-before-publication after a process loss.
            queued = self.state.execute(
                "SELECT v.url,v.depth FROM visited v LEFT JOIN frontier f "
                "ON f.execution_id=v.execution_id AND f.url_hash=v.url_hash "
                "WHERE v.execution_id=? AND v.status='queued' AND f.sequence IS NULL",
                (execution_id,),
            ).fetchall()
            if queued:
                await frontier.push(
                    [FrontierUrl(url=row["url"], depth=row["depth"]) for row in queued]
                )
            engine = CrawlEngine(
                engine_ports(
                    fetcher=http,
                    robots=RobotsService(
                        robots_http, SQLiteRobotsCache(self.state), clock
                    ),
                    visited=visited,
                    gate=SQLiteHostGate(self.state, clock),
                    frontier=frontier,
                    pages=writer,
                    records=writer,
                    clock=clock,
                ),
                park_threshold_s=float("inf"),
                should_stop=should_stop,
                admission_remaining=max(intent.scope.max_pages - admitted, 0),
            )
            yield SimpleNamespace(
                intent=intent,
                writer=writer,
                engine=engine,
                admitted=admitted,
                frontier=frontier,
            )
