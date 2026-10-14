"""Compose an in-memory crawl with the shared transport resource owner."""

from pulsecrawl.bootstrap.crawling import fetch_resources, engine_ports
from pulsecrawl.application.crawling.engine import CrawlEngine
from pulsecrawl.application.crawling.robots import RobotsService
from pulsecrawl.adapters.outbound.memory.crawling import (
    SystemClock,
    MemoryRecordSink,
    MemoryRobotsCache,
    MemoryVisitedStore,
    MemoryHostGate,
    MemoryPendingUrls,
    MemoryPageSink,
)
from pulsecrawl.adapters.outbound.memory.records import TeeRecordSink


async def run_ephemeral(
    intent,
    *,
    fetcher=None,
    allow_private_networks=False,
    page_sink=None,
    record_sink=None,
    collect_records=True,
):
    clock, sink = SystemClock(), MemoryRecordSink()
    async with fetch_resources(
        fetcher=fetcher, allow_private_networks=allow_private_networks
    ) as (http, robots):
        engine = CrawlEngine(
            engine_ports(
                fetcher=http,
                robots=RobotsService(robots, MemoryRobotsCache(), clock),
                visited=MemoryVisitedStore(),
                gate=MemoryHostGate(clock),
                pending_urls=MemoryPendingUrls(),
                pages=page_sink if page_sink is not None else MemoryPageSink(),
                records=TeeRecordSink(sink, record_sink, collect_records),
                clock=clock,
            ),
            park_threshold_s=float("inf"),
        )
        await engine.seed(intent)
        outcome = await engine.run(intent)
    return sink.records, outcome
