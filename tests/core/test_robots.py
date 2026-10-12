from pulsecrawl.core.adapters.memory import FakeClock, MemoryRobotsCache
from pulsecrawl.core.model import Politeness
from pulsecrawl.core.robots import RobotsService

from .conftest import FakeFetcher

ROBOTS = """
User-agent: *
Disallow: /private/
Crawl-delay: 5
"""

POLITE = Politeness()


def make_service(fetcher, clock, ttl=3600.0):
    return RobotsService(fetcher, MemoryRobotsCache(), clock, ttl_s=ttl)


class TestRobotsService:
    async def test_evaluates_each_url_against_full_ruleset(self):
        fetcher = FakeFetcher()
        fetcher.add("https://x.example/robots.txt", ROBOTS)
        service = make_service(fetcher, FakeClock())

        allowed, delay = await service.check("https://x.example/ok", POLITE)
        assert allowed and delay == 5.0
        blocked, _ = await service.check("https://x.example/private/a", POLITE)
        assert not blocked

    async def test_caches_text_within_ttl(self):
        fetcher = FakeFetcher()
        fetcher.add("https://x.example/robots.txt", ROBOTS)
        clock = FakeClock()
        service = make_service(fetcher, clock)

        await service.check("https://x.example/a", POLITE)
        await service.check("https://x.example/b", POLITE)
        assert fetcher.calls.count("https://x.example/robots.txt") == 1

        clock.advance(3601)
        await service.check("https://x.example/c", POLITE)
        assert fetcher.calls.count("https://x.example/robots.txt") == 2

    async def test_unreachable_robots_allows_all_with_no_delay(self):
        fetcher = FakeFetcher()  # 404 for everything
        service = make_service(fetcher, FakeClock())
        allowed, delay = await service.check("https://x.example/anything", POLITE)
        assert allowed and delay is None

    async def test_server_failure_fails_closed_and_is_cached(self):
        fetcher = FakeFetcher()
        fetcher.add("https://x.example/robots.txt", "down", status=503)
        service = make_service(fetcher, FakeClock())
        first = await service.check("https://x.example/anything", POLITE)
        second = await service.check("https://x.example/anything", POLITE)
        assert not first.allowed and first.fetch_failed and first.fetched
        assert not second.allowed and second.fetch_failed and second.cache_hit
        assert fetcher.calls.count("https://x.example/robots.txt") == 1

    async def test_network_robots_read_runs_through_request_gate(self):
        fetcher = FakeFetcher()
        fetcher.add("https://x.example/robots.txt", "User-agent: *\nAllow: /")
        service = make_service(fetcher, FakeClock())
        gated = []

        async def before_fetch(url):
            gated.append(url)

        decision = await service.check(
            "https://x.example/a", POLITE, before_fetch=before_fetch
        )
        assert decision.allowed
        assert gated == ["https://x.example/robots.txt"]

    async def test_no_crawl_delay_directive_returns_none(self):
        fetcher = FakeFetcher()
        fetcher.add("https://x.example/robots.txt", "User-agent: *\nDisallow: /admin/\n")
        service = make_service(fetcher, FakeClock())
        allowed, delay = await service.check("https://x.example/a", POLITE)
        assert allowed and delay is None
