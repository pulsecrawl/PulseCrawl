"""Behavioral contracts every adapter implementation must satisfy.

When Redis/Azure adapters exist, they get registered here and must pass
the identical assertions.
"""
import pytest

from pulsecrawl.core.adapters.memory import (
    FakeClock,
    MemoryPendingUrls,
    MemoryHostGate,
    MemoryVisitedStore,
)
from pulsecrawl.core.model import PendingUrl, VisitedRow
from pulsecrawl.core.politeness import guarded_interval_s


class TestHostGateContract:
    async def test_schedule_allocates_ordered_future_slots(self):
        clock = FakeClock()
        gate = MemoryHostGate(clock, platform_requests_per_second=1000)

        assert await gate.schedule("org_a", "https://x.example", 2.0, 0.0) == 0.0
        assert await gate.schedule("org_a", "https://x.example", 2.0, 0.0) == pytest.approx(2.2)
        assert await gate.schedule("org_a", "https://x.example", 2.0, 0.0) == pytest.approx(4.4)

    async def test_schedules_share_platform_but_not_org_windows(self):
        clock = FakeClock()
        gate = MemoryHostGate(clock, platform_requests_per_second=2)

        assert await gate.schedule("org_a", "https://x.example", 2.0, 0.0) == 0.0
        assert await gate.schedule("org_b", "https://x.example", 2.0, 0.0) == pytest.approx(0.55)

    async def test_schedule_never_falls_behind_live_dispatch(self):
        clock = FakeClock()
        gate = MemoryHostGate(clock, platform_requests_per_second=1000)

        assert await gate.reserve("org_a", "https://x.example", 3.0, 0.0) == 0.0
        assert await gate.schedule("org_a", "https://x.example", 3.0, 0.0) == pytest.approx(3.3)

    async def test_grant_consumes_slot(self):
        clock = FakeClock()
        gate = MemoryHostGate(clock)
        assert await gate.reserve("org_a", "https://x.example", 10.0, 0.0) == 0.0
        wait = await gate.reserve("org_a", "https://x.example", 10.0, 0.0)
        assert wait == pytest.approx(11.0)

    async def test_deferral_does_not_advance_the_window(self):
        """A burst of deferred callers must not snowball the host's delay."""
        clock = FakeClock()
        gate = MemoryHostGate(clock)
        await gate.reserve("org_a", "https://x.example", 10.0, 0.0)

        first_wait = await gate.reserve("org_a", "https://x.example", 10.0, 0.0)
        for _ in range(50):  # hammering while blocked changes nothing
            await gate.reserve("org_a", "https://x.example", 10.0, 0.0)
        assert await gate.reserve("org_a", "https://x.example", 10.0, 0.0) == first_wait

        clock.advance(first_wait)
        assert await gate.reserve("org_a", "https://x.example", 10.0, 0.0) == 0.0

    async def test_hosts_are_independent(self):
        clock = FakeClock()
        gate = MemoryHostGate(clock)
        assert await gate.reserve("org_a", "https://a.example", 10.0, 0.0) == 0.0
        assert await gate.reserve("org_a", "https://b.example", 10.0, 0.0) == 0.0

    async def test_jobs_in_one_org_share_the_origin_window(self):
        clock = FakeClock()
        gate = MemoryHostGate(clock, platform_requests_per_second=1000)
        assert await gate.reserve("org_a", "https://x.example", 2.0, 0.0) == 0.0
        assert await gate.reserve("org_a", "https://x.example", 2.0, 0.0) == pytest.approx(2.2)

    async def test_org_windows_are_independent_but_share_platform_safety(self):
        clock = FakeClock()
        gate = MemoryHostGate(clock, platform_requests_per_second=2)
        assert await gate.reserve("org_a", "https://x.example", 1.0, 0.0) == 0.0
        assert await gate.reserve("org_b", "https://x.example", 1.0, 0.0) == pytest.approx(0.55)
        clock.advance(0.55)
        assert await gate.reserve("org_b", "https://x.example", 1.0, 0.0) == 0.0

    async def test_robots_delay_strengthens_platform_window(self):
        clock = FakeClock()
        gate = MemoryHostGate(clock, platform_requests_per_second=100)
        assert await gate.reserve("org_a", "https://x.example", 2.0, 2.0) == 0.0
        assert await gate.reserve("org_b", "https://x.example", 2.0, 2.0) == pytest.approx(2.2)

    def test_dispatch_margin_is_conservative_and_validated(self):
        assert guarded_interval_s(0.5) == pytest.approx(0.55)
        assert guarded_interval_s(0.5, 0.0) == 0.5
        with pytest.raises(ValueError, match="interval_s"):
            guarded_interval_s(-0.1)
        with pytest.raises(ValueError, match="margin_ratio"):
            guarded_interval_s(0.5, -0.1)


class TestPendingUrlsContract:
    async def test_orders_by_not_before_then_fifo(self):
        pending_urls = MemoryPendingUrls()
        await pending_urls.push(
            [
                PendingUrl(url="https://x/1", depth=0, not_before=100.0),
                PendingUrl(url="https://x/2", depth=0, not_before=50.0),
                PendingUrl(url="https://x/3", depth=0, not_before=50.0),
            ]
        )
        assert (await pending_urls.pop_ready(200.0)).url == "https://x/2"
        assert (await pending_urls.pop_ready(200.0)).url == "https://x/3"
        assert (await pending_urls.pop_ready(200.0)).url == "https://x/1"

    async def test_never_returns_future_items(self):
        pending_urls = MemoryPendingUrls()
        await pending_urls.push([PendingUrl(url="https://x/1", depth=0, not_before=100.0)])
        assert await pending_urls.pop_ready(99.0) is None
        assert await pending_urls.next_ready_at() == 100.0
        assert (await pending_urls.pop_ready(100.0)).url == "https://x/1"

    async def test_empty_pending_urls(self):
        pending_urls = MemoryPendingUrls()
        assert await pending_urls.pop_ready(0.0) is None
        assert await pending_urls.next_ready_at() is None


class TestVisitedStoreContract:
    async def test_queued_is_admitted_but_not_yet_seen(self):
        store = MemoryVisitedStore()
        queued = VisitedRow(url_hash="h1", url="https://x/1", status="queued", depth=0)
        await store.add("exec_a", [queued])
        assert await store.admitted("exec_a", "h1")
        assert not await store.seen("exec_a", "h1")

        fetched = VisitedRow(url_hash="h1", url="https://x/1", status="fetched", depth=0)
        await store.add("exec_a", [fetched])
        assert await store.seen("exec_a", "h1")
        assert len(store.rows["exec_a"]) == 1

    async def test_seen_is_per_execution(self):
        store = MemoryVisitedStore()
        row = VisitedRow(url_hash="h1", url="https://x/1", status="fetched", depth=0)
        await store.add("exec_a", [row])
        assert await store.seen("exec_a", "h1")
        assert not await store.seen("exec_b", "h1")
        assert not await store.seen("exec_a", "h2")

    async def test_preload_supports_resume(self):
        store = MemoryVisitedStore()
        store.preload("exec_a", ["h1", "h2"])
        assert await store.seen("exec_a", "h1")
        assert await store.seen("exec_a", "h2")
