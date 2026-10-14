"""The same behavioral assertions run against memory and durable SQLite ports."""

from types import SimpleNamespace
import time
import pytest

from pulsecrawl import Workspace
from pulsecrawl.adapters.outbound.memory.crawling import (
    FakeClock,
    MemoryPendingUrls,
    MemoryHostGate,
    MemoryVisitedStore,
    MemoryRobotsCache,
)
from pulsecrawl.adapters.outbound.sqlite.crawling import (
    SQLitePendingUrls,
    SQLiteHostGate,
    SQLiteVisitedStore,
    SQLiteRobotsCache,
)
from pulsecrawl.adapters.outbound.sqlite.clock import EpochClock
from pulsecrawl.application.time import readiness_time
from pulsecrawl.domain.crawling.model import PendingUrl, VisitedRow, RobotsCacheEntry
from pulsecrawl.domain.crawling.urls import url_hash


@pytest.fixture(params=["memory", "sqlite"])
def backend(request, tmp_path):
    clock = FakeClock()
    if request.param == "memory":
        yield SimpleNamespace(
            pending_urls=MemoryPendingUrls(),
            gate=MemoryHostGate(clock),
            visited=MemoryVisitedStore(),
            robots=MemoryRobotsCache(),
            clock=clock,
            execution_id="e",
        )
        return
    with Workspace.init(tmp_path / "workspace") as workspace:
        dataset = workspace.datasets.create(
            "d", fields=[{"fieldId": "title", "name": "title", "type": "string"}]
        )
        job = workspace.jobs.create(
            "j",
            seeds=["https://example.com"],
            dataset_id=dataset["datasetId"],
            templates=[{"engine": "css", "mappings": {"title": "h1"}}],
        )
        execution = workspace.jobs.prepare(job["jobId"])
        execution_id = execution["executionId"]
        yield SimpleNamespace(
            pending_urls=SQLitePendingUrls(workspace.state, execution_id),
            gate=SQLiteHostGate(workspace.state, clock),
            visited=SQLiteVisitedStore(workspace.state),
            robots=SQLiteRobotsCache(workspace.state),
            clock=clock,
            execution_id=execution_id,
        )


async def test_pending_urls_never_returns_future_work_and_preserves_fifo_ties(backend):
    items = [
        PendingUrl("https://example.com/late", 0, 1100),
        PendingUrl("https://example.com/first", 0, 1050),
        PendingUrl("https://example.com/second", 0, 1050),
    ]
    await backend.pending_urls.push(items)
    assert await backend.pending_urls.pop_ready(1049) is None
    assert await backend.pending_urls.next_ready_at() == 1050
    assert (await backend.pending_urls.pop_ready(1050)).url.endswith("/first")
    assert (await backend.pending_urls.pop_ready(1050)).url.endswith("/second")
    assert await backend.pending_urls.pop_ready(1050) is None
    assert (await backend.pending_urls.pop_ready(1100)).url.endswith("/late")


async def test_admission_is_not_completion_and_is_execution_scoped(backend):
    url = "https://example.com/a"
    hashed = url_hash(url)
    row = VisitedRow(hashed, url, "queued", 0)
    await backend.visited.add(backend.execution_id, [row])
    assert await backend.visited.admitted(backend.execution_id, hashed)
    assert not await backend.visited.seen(backend.execution_id, hashed)
    assert not await backend.visited.admitted("other", hashed)
    await backend.visited.add(
        backend.execution_id, [VisitedRow(hashed, url, "fetched", 0)]
    )
    assert await backend.visited.seen(backend.execution_id, hashed)


async def test_rate_deferrals_never_consume_additional_live_slots(backend):
    args = ("org", "https://example.com", 2.0, 0.0)
    assert await backend.gate.reserve(*args) == 0
    delay = await backend.gate.reserve(*args)
    assert delay > 2
    for _ in range(10):
        assert await backend.gate.reserve(*args) == pytest.approx(delay)
    backend.clock.advance(delay)
    assert await backend.gate.reserve(*args) == 0


async def test_schedule_allocates_distinct_future_slots(backend):
    args = ("org", "https://example.com", 2.0, 0.0)
    assert await backend.gate.schedule(*args) == 0
    first = await backend.gate.schedule(*args)
    assert first > 2
    assert await backend.gate.schedule(*args) == pytest.approx(first * 2)


async def test_robots_cache_preserves_fetch_failure_metadata(backend):
    origin = "https://example.com"
    assert await backend.robots.get(origin) is None
    entry = RobotsCacheEntry("User-agent: *\nDisallow: /", 1000, True)
    await backend.robots.put(origin, entry)
    assert await backend.robots.get(origin) == entry


def test_persistent_readiness_is_epoch_not_process_uptime():
    before = time.time()
    clock = EpochClock()
    assert before <= readiness_time(clock) <= time.time()
    assert abs(clock.elapsed_time() - time.monotonic()) < 1
    assert abs(clock.monotonic() - time.time()) < 1  # Compatibility coordinate.
