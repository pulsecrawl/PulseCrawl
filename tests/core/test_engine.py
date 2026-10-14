from dataclasses import replace
from datetime import datetime, timezone

import pytest

from pulsecrawl.core.engine import CrawlEngine
from pulsecrawl.core.model import (
    Completed,
    FetchResult,
    PendingUrl,
    Parked,
    Politeness,
    Scope,
)
from pulsecrawl.core.urls import url_hash

from .conftest import make_intent

SITE = "https://shop.example"

PRODUCT = """
<html><body>
  <h1>{name}</h1><span class="price">{price}</span>
  {links}
</body></html>
"""


def add_site(fetcher):
    fetcher.add(
        f"{SITE}/",
        PRODUCT.format(
            name="Home", price="$1.00",
            links='<a href="/p/1">1</a><a href="/p/2">2</a><a href="https://other.example/x">ext</a>',
        ),
    )
    fetcher.add(f"{SITE}/p/1", PRODUCT.format(name="One", price="$10.00", links='<a href="/p/2">2</a>'))
    fetcher.add(f"{SITE}/p/2", PRODUCT.format(name="Two", price="$20.00", links=""))


class TestCrawlEndToEnd:
    async def test_same_site_redirect_is_a_separate_scoped_budgeted_hop(self, ports):
        start = f"{SITE}/old"
        target = f"{SITE}/new"

        class RedirectFetcher:
            def __init__(self):
                self.calls = []

            async def fetch(self, requested, *, user_agent):
                self.calls.append(requested)
                if requested == start:
                    return FetchResult(
                        url=requested,
                        final_url=requested,
                        status=302,
                        headers={"Location": "/new"},
                        body=None,
                        error="HTTP 302",
                        fetched_at=datetime.now(timezone.utc),
                    )
                return FetchResult(
                    url=requested,
                    final_url=requested,
                    status=200,
                    headers={"Content-Type": "text/html"},
                    body=PRODUCT.format(name="Redirected", price="$9", links=""),
                    error=None,
                    fetched_at=datetime.now(timezone.utc),
                )

        fetcher = RedirectFetcher()
        ports.fetcher = fetcher
        intent = make_intent(
            seeds=(start,),
            scope=Scope(max_pages=2),
            politeness=Politeness(respect_robots_txt=False, requests_per_second=1000),
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)

        assert fetcher.calls == [start, target]
        assert outcome.stats.urls_attempted == 2
        assert outcome.stats.pages_discovered == 1
        assert outcome.stats.pages_fetched == 1
        assert [record.fields["title"] for record in ports.records.records] == ["Redirected"]
        status = {row.url: row.status for row in ports.visited.rows[intent.execution_id]}
        assert status == {start: "skipped", target: "fetched"}

    async def test_redirect_cannot_escape_scope_or_bypass_attempt_budget(self, ports):
        start = f"{SITE}/leave"

        class OffsiteRedirect:
            calls = []

            async def fetch(self, requested, *, user_agent):
                self.calls.append(requested)
                return FetchResult(
                    url=requested,
                    final_url=requested,
                    status=302,
                    headers={"location": "https://outside.example/private"},
                    body=None,
                    error="HTTP 302",
                    fetched_at=datetime.now(timezone.utc),
                )

        fetcher = OffsiteRedirect()
        ports.fetcher = fetcher
        intent = make_intent(
            seeds=(start,),
            scope=Scope(max_pages=10, same_domain_only=True),
            politeness=Politeness(respect_robots_txt=False, requests_per_second=1000),
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)

        assert fetcher.calls == [start]
        assert outcome.stats.urls_attempted == 1
        assert outcome.stats.pages_discovered == 0
        assert len(ports.visited.rows[intent.execution_id]) == 1

    async def test_redirect_loop_terminates_through_durable_dedup(self, ports):
        first, second = f"{SITE}/one", f"{SITE}/two"

        class LoopingFetcher:
            def __init__(self):
                self.calls = []

            async def fetch(self, requested, *, user_agent):
                self.calls.append(requested)
                target = "/two" if requested == first else "/one"
                return FetchResult(
                    url=requested,
                    final_url=requested,
                    status=301,
                    headers={"Location": target},
                    body=None,
                    error="HTTP 301",
                    fetched_at=datetime.now(timezone.utc),
                )

        fetcher = LoopingFetcher()
        ports.fetcher = fetcher
        intent = make_intent(
            seeds=(first,),
            scope=Scope(max_pages=10),
            politeness=Politeness(respect_robots_txt=False, requests_per_second=1000),
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)

        assert fetcher.calls == [first, second]
        assert outcome.stats.urls_attempted == 2
        assert outcome.stats.pages_discovered == 1
        assert await ports.pending_urls.next_ready_at() is None

    async def test_redirect_without_valid_location_is_terminal_and_visible(self, ports):
        start = f"{SITE}/broken-redirect"

        class BrokenRedirect:
            async def fetch(self, requested, *, user_agent):
                return FetchResult(
                    url=requested,
                    final_url=requested,
                    status=307,
                    headers={"Location": "javascript:alert(1)"},
                    body=None,
                    error="HTTP 307",
                    fetched_at=datetime.now(timezone.utc),
                )

        ports.fetcher = BrokenRedirect()
        intent = make_intent(
            seeds=(start,),
            politeness=Politeness(respect_robots_txt=False, requests_per_second=1000),
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)
        [visited] = ports.visited.rows[intent.execution_id]
        assert outcome.stats.urls_attempted == 1
        assert visited.status == "skipped"
        assert visited.error == "redirect without valid location"

    async def test_transient_response_retries_through_pending_urls_and_gate(self, ports):
        url = f"{SITE}/busy"

        class RecoveringFetcher:
            calls = 0

            async def fetch(self, requested, *, user_agent):
                self.calls += 1
                if self.calls == 1:
                    return FetchResult(
                        url=requested,
                        final_url=requested,
                        status=503,
                        headers={"Retry-After": "7"},
                        body=None,
                        error="HTTP 503",
                        fetched_at=datetime.now(timezone.utc),
                    )
                return FetchResult(
                    url=requested,
                    final_url=requested,
                    status=200,
                    headers={"Content-Type": "text/html"},
                    body=PRODUCT.format(name="Ready", price="$1", links=""),
                    error=None,
                    fetched_at=datetime.now(timezone.utc),
                )

        fetcher = RecoveringFetcher()
        ports.fetcher = fetcher
        intent = make_intent(
            seeds=(url,),
            scope=Scope(max_pages=5),
            politeness=Politeness(
                respect_robots_txt=False,
                requests_per_second=1000,
                organization_requests_per_second=1000,
            ),
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        started = ports.clock.monotonic()

        outcome = await engine.run(intent)

        assert outcome.stats.urls_attempted == 2
        assert outcome.stats.transient_retries == 1
        assert outcome.stats.pages_fetched == 1
        assert ports.clock.monotonic() - started >= 7

    async def test_transient_retries_are_bounded(self, ports):
        url = f"{SITE}/always-busy"

        class BusyFetcher:
            async def fetch(self, requested, *, user_agent):
                return FetchResult(
                    url=requested,
                    final_url=requested,
                    status=429,
                    headers={"Retry-After": "invalid"},
                    body=None,
                    error="HTTP 429",
                    fetched_at=datetime.now(timezone.utc),
                )

        ports.fetcher = BusyFetcher()
        intent = make_intent(
            seeds=(url,),
            scope=Scope(max_pages=10),
            politeness=Politeness(respect_robots_txt=False, requests_per_second=1000),
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)

        outcome = await engine.run(intent)

        assert outcome.stats.urls_attempted == 4
        assert outcome.stats.transient_retries == 3
        assert outcome.stats.pages_failed == 1

    async def test_host_schedule_staggers_urls_without_repeated_gate_deferrals(
        self, ports, fetcher
    ):
        urls = tuple(f"{SITE}/scheduled-{index}" for index in range(3))
        for index, url in enumerate(urls):
            fetcher.add(
                url,
                PRODUCT.format(name=f"Scheduled {index}", price="$1.00", links=""),
            )
        intent = make_intent(
            seeds=urls,
            scope=Scope(max_pages=3),
            politeness=Politeness(
                respect_robots_txt=False,
                requests_per_second=1.0,
                organization_requests_per_second=1.0,
            ),
        )
        schedule_calls = 0
        reserve_calls = 0
        original_schedule = ports.gate.schedule
        original_reserve = ports.gate.reserve

        async def counted_schedule(*args):
            nonlocal schedule_calls
            schedule_calls += 1
            return await original_schedule(*args)

        async def counted_reserve(*args):
            nonlocal reserve_calls
            reserve_calls += 1
            return await original_reserve(*args)

        ports.gate.schedule = counted_schedule
        ports.gate.reserve = counted_reserve
        engine = CrawlEngine(ports, inline_wait_s=0.0)
        await engine.seed(intent)

        outcome = await engine.run(intent)

        assert outcome.stats.urls_attempted == 3
        assert schedule_calls == 3  # one authoritative allocation per URL
        assert reserve_calls == 3  # one cheap Redis dispatch permit per HTTP request
        assert outcome.stats.rate_limit_deferrals == 0
        assert outcome.stats.rate_limit_queue_deferrals == 2
        assert outcome.stats.rate_limit_queue_wait_seconds == pytest.approx(3.3)

    async def test_subsecond_rate_uses_precise_inline_timer(self, ports, fetcher):
        urls = tuple(f"{SITE}/fast-{index}" for index in range(3))
        for index, url in enumerate(urls):
            fetcher.add(
                url,
                PRODUCT.format(name=f"Fast {index}", price="$1.00", links=""),
            )
        intent = make_intent(
            seeds=urls,
            scope=Scope(max_pages=3),
            politeness=Politeness(
                respect_robots_txt=False,
                requests_per_second=5.0,
                organization_requests_per_second=5.0,
            ),
        )
        engine = CrawlEngine(ports, inline_wait_s=0.25)
        await engine.seed(intent)
        started = ports.clock.monotonic()

        outcome = await engine.run(intent)

        assert outcome.stats.urls_attempted == 3
        assert outcome.stats.rate_limit_deferrals == 0
        assert outcome.stats.rate_limit_queue_deferrals == 2
        assert round(outcome.stats.rate_limit_queue_wait_seconds, 6) == 0.66
        assert round(ports.clock.monotonic() - started, 6) == 0.44

    async def test_dispatch_lane_preserves_rate_without_visibility_guard_band(
        self, ports, fetcher
    ):
        urls = tuple(f"{SITE}/guarded-{index}" for index in range(3))
        for index, url in enumerate(urls):
            fetcher.add(
                url,
                PRODUCT.format(name=f"Guarded {index}", price="$1.00", links=""),
            )
        intent = make_intent(
            seeds=urls,
            scope=Scope(max_pages=3),
            politeness=Politeness(
                respect_robots_txt=False,
                requests_per_second=1.0,
                organization_requests_per_second=1.0,
            ),
        )
        engine = CrawlEngine(
            ports,
            inline_wait_s=0.0,
            queue_visibility_resolution_s=1.0,
        )
        await engine.seed(intent)
        started = ports.clock.monotonic()

        outcome = await engine.run(intent)

        assert outcome.stats.urls_attempted == 3
        assert outcome.stats.rate_limit_queue_deferrals == 2
        assert outcome.stats.rate_limit_queue_wait_seconds == pytest.approx(3.3)
        assert ports.clock.monotonic() - started == pytest.approx(2.2)

    async def test_stale_visibility_slot_uses_current_dispatch_lane(self, ports, fetcher):
        url = f"{SITE}/stale-slot"
        fetcher.add(url, PRODUCT.format(name="Stale", price="$1.00", links=""))
        intent = make_intent(
            seeds=(url,),
            scope=Scope(max_pages=1),
            politeness=Politeness(respect_robots_txt=False, requests_per_second=1.0),
        )
        engine = CrawlEngine(ports, inline_wait_s=0.0)
        await engine.seed(intent)
        queued = await ports.pending_urls.pop_ready(ports.clock.monotonic())
        await ports.pending_urls.push(
            [
                PendingUrl(
                    url=queued.url,
                    depth=queued.depth,
                    rate_scheduled=True,
                    rate_slot_expires_at=ports.clock.now().timestamp() - 1,
                )
            ]
        )
        # Another execution used the origin just now. The stale admission is
        # delayed only by that current permit, not by the future schedule tail.
        assert await ports.gate.reserve(
            intent.org_id, SITE, 1.0, 0.0
        ) == 0.0
        started = ports.clock.monotonic()

        outcome = await engine.run(intent)

        assert outcome.stats.urls_attempted == 1
        assert outcome.stats.rate_limit_deferrals == 1
        assert outcome.stats.rate_limit_queue_deferrals == 1
        assert ports.clock.monotonic() - started == pytest.approx(1.1)

    async def test_inline_dispatch_wait_reacquires_before_http(self, ports, fetcher):
        url = f"{SITE}/inline-recheck"
        fetcher.add(url, PRODUCT.format(name="Recheck", price="$1.00", links=""))
        intent = make_intent(
            seeds=(url,),
            scope=Scope(max_pages=1),
            politeness=Politeness(respect_robots_txt=False, requests_per_second=5.0),
        )
        engine = CrawlEngine(ports, inline_wait_s=0.25)
        await engine.seed(intent)
        started = ports.clock.monotonic()
        waits = iter((0.2, 0.2, 0.0))
        calls = 0

        async def contended_reserve(*_args):
            nonlocal calls
            calls += 1
            return next(waits)

        ports.gate.reserve = contended_reserve
        outcome = await engine.run(intent)

        assert outcome.stats.urls_attempted == 1
        assert calls == 3
        assert round(ports.clock.monotonic() - started, 6) == 0.4

    async def test_crawls_dedupes_and_extracts(self, ports, fetcher):
        add_site(fetcher)
        intent = make_intent(seeds=(f"{SITE}/",))
        engine = CrawlEngine(ports)
        assert await engine.seed(intent) == 1

        outcome = await engine.run(intent)

        assert isinstance(outcome, Completed)
        assert outcome.stats.pages_fetched == 3        # /, /p/1, /p/2: p/2 only once
        assert outcome.stats.records_extracted == 3
        assert outcome.stats.pages_discovered == 2     # unique URLs admitted to the pending_urls
        titles = {r.fields["title"] for r in ports.records.records}
        assert titles == {"Home", "One", "Two"}
        prices = {r.fields["price"] for r in ports.records.records}
        assert prices == {1.0, 10.0, 20.0}
        # off-site link never fetched
        assert all("other.example" not in url for url in fetcher.calls)

    async def test_output_failure_does_not_mark_url_processed(self, ports, fetcher):
        """A replay must remain possible until every page output is durable."""
        fetcher.add(
            f"{SITE}/",
            PRODUCT.format(name="Home", price="$1.00", links=""),
        )
        intent = make_intent(
            seeds=(f"{SITE}/",),
            politeness=Politeness(
                respect_robots_txt=False,
                requests_per_second=1000.0,
            ),
        )

        async def fail_emit(_records):
            raise RuntimeError("record sink unavailable")

        ports.records.emit = fail_emit
        engine = CrawlEngine(ports)
        await engine.seed(intent)

        with pytest.raises(RuntimeError, match="record sink unavailable"):
            await engine.run(intent)

        [row] = ports.visited.rows[intent.execution_id]
        assert row.status == "queued"
        assert not await ports.visited.seen(intent.execution_id, row.url_hash)

    async def test_snapshots_saved_unless_disabled(self, ports, fetcher):
        add_site(fetcher)
        intent = make_intent(seeds=(f"{SITE}/",), store_raw_pages=True)
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        await engine.run(intent)
        assert url_hash(f"{SITE}/") in ports.pages.pages
        snapshot = ports.pages.pages[url_hash(f"{SITE}/")]
        assert snapshot.status == 200 and "Home" in snapshot.body
        assert snapshot.body_truncated is False

    async def test_snapshot_preserves_partial_body_provenance(self, ports, fetcher):
        fetcher.add(f"{SITE}/", "<h1>cut")
        original_fetch = fetcher.fetch

        async def truncated_fetch(*args, **kwargs):
            result = await original_fetch(*args, **kwargs)
            return replace(result, body_truncated=True, body_bytes=7)

        fetcher.fetch = truncated_fetch
        intent = make_intent(
            seeds=(f"{SITE}/",),
            politeness=Politeness(respect_robots_txt=False, requests_per_second=1000),
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        await engine.run(intent)

        snapshot = ports.pages.pages[url_hash(f"{SITE}/")]
        assert snapshot.body_truncated is True
        assert snapshot.body_bytes == 7

    async def test_store_raw_pages_off(self, ports, fetcher):
        add_site(fetcher)
        intent = make_intent(seeds=(f"{SITE}/",), store_raw_pages=False)
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        await engine.run(intent)
        assert ports.pages.pages == {}

    async def test_max_pages_caps_fetches(self, ports, fetcher):
        add_site(fetcher)
        intent = make_intent(seeds=(f"{SITE}/",), scope=Scope(max_pages=1))
        engine = CrawlEngine(ports)
        seen_calls = 0
        original_seen = ports.visited.seen

        async def counted_seen(execution_id, hashed):
            nonlocal seen_calls
            seen_calls += 1
            return await original_seen(execution_id, hashed)

        ports.visited.seen = counted_seen
        await engine.seed(intent)
        outcome = await engine.run(intent)
        assert outcome.stats.pages_fetched == 1
        assert outcome.stats.urls_attempted == 1
        # Once the only admission slot is consumed, links on the fetched page
        # must not trigger visited-store lookups that cannot enqueue anything.
        assert seen_calls == 1

    async def test_budget_caps_seed_admission(self, ports, fetcher):
        intent = make_intent(
            seeds=(f"{SITE}/missing-1", f"{SITE}/missing-2"),
            scope=Scope(max_pages=1),
            politeness=Politeness(respect_robots_txt=False, requests_per_second=1000.0),
        )
        engine = CrawlEngine(ports)
        assert await engine.seed(intent) == 1
        outcome = await engine.run(intent)
        assert outcome.stats.urls_attempted == 1
        assert len(fetcher.calls) == 1
        assert await ports.pending_urls.next_ready_at() is None

    async def test_budget_caps_discovery_admission(self, ports, fetcher):
        add_site(fetcher)
        intent = make_intent(
            seeds=(f"{SITE}/",),
            scope=Scope(max_pages=2),
            politeness=Politeness(respect_robots_txt=False, requests_per_second=1000.0),
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)
        assert outcome.stats.urls_attempted == 2
        assert outcome.stats.pages_discovered == 1
        assert len(fetcher.calls) == 2
        assert await ports.pending_urls.next_ready_at() is None

    async def test_failed_requests_consume_attempt_budget(self, ports, fetcher):
        intent = make_intent(
            seeds=(f"{SITE}/missing-1", f"{SITE}/missing-2"),
            scope=Scope(max_pages=1),
            politeness=Politeness(respect_robots_txt=False, requests_per_second=1000.0),
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)
        assert outcome.stats.urls_attempted == 1
        assert outcome.stats.pages_failed == 1
        assert outcome.stats.pages_fetched == 0
        assert len(fetcher.calls) == 1

    async def test_max_depth_stops_discovery(self, ports, fetcher):
        add_site(fetcher)
        intent = make_intent(seeds=(f"{SITE}/",), scope=Scope(max_depth=0, max_pages=50))
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)
        assert outcome.stats.pages_fetched == 1        # depth-0 seed only
        assert outcome.stats.pages_discovered == 0

    async def test_failed_pages_counted_and_marked(self, ports, fetcher):
        fetcher.add(f"{SITE}/", PRODUCT.format(name="Home", price="$1", links='<a href="/gone">x</a>'))
        intent = make_intent(seeds=(f"{SITE}/",))
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)
        assert outcome.stats.pages_failed == 1
        rows = ports.visited.rows["exec_test"]
        assert any(r.status == "failed" and r.url.endswith("/gone") for r in rows)

    async def test_robots_blocked_pages_are_skipped(self, ports, fetcher):
        fetcher.add(
            f"{SITE}/robots.txt", "User-agent: *\nDisallow: /p/\n", content_type="text/plain"
        )
        add_site(fetcher)
        intent = make_intent(seeds=(f"{SITE}/",))
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)
        assert outcome.stats.pages_fetched == 1
        rows = ports.visited.rows["exec_test"]
        assert sum(1 for r in rows if r.status == "robots_blocked") == 2
        assert outcome.stats.robots_blocked == 2
        assert outcome.stats.robots_fetches == 1
        assert outcome.stats.robots_cache_hits == 2

    async def test_robots_disabled_skips_check(self, ports, fetcher):
        fetcher.add(f"{SITE}/robots.txt", "User-agent: *\nDisallow: /\n", content_type="text/plain")
        add_site(fetcher)
        intent = make_intent(
            seeds=(f"{SITE}/",),
            politeness=Politeness(respect_robots_txt=False, requests_per_second=1000.0),
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)
        assert outcome.stats.pages_fetched == 3

    async def test_politeness_defers_and_sleeps(self, ports, fetcher, clock):
        add_site(fetcher)
        intent = make_intent(
            seeds=(f"{SITE}/",), politeness=Politeness(requests_per_second=0.5)
        )  # 2s between hits
        engine = CrawlEngine(ports, park_threshold_s=60.0)
        await engine.seed(intent)
        outcome = await engine.run(intent)
        assert outcome.stats.pages_fetched == 3
        assert any(s > 0 for s in clock.sleeps)        # actually waited between fetches

    async def test_parks_when_wait_exceeds_threshold(self, ports, fetcher, clock):
        add_site(fetcher)
        intent = make_intent(
            seeds=(f"{SITE}/",), politeness=Politeness(requests_per_second=0.01)
        )  # 100s between hits
        engine = CrawlEngine(ports, park_threshold_s=30.0)
        await engine.seed(intent)
        outcome = await engine.run(intent)
        assert isinstance(outcome, Parked)
        # The robots network read consumes the first origin slot; the page is
        # safely parked rather than immediately following it.
        assert outcome.stats.pages_fetched == 0
        assert 109.0 <= outcome.resume_after_s <= 110.0

    async def test_should_stop_cancels_promptly(self, ports, fetcher):
        add_site(fetcher)
        fetches = 0

        def stop_after_first():
            return fetches >= 1

        intent = make_intent(seeds=(f"{SITE}/",))
        engine = CrawlEngine(ports, should_stop=stop_after_first)
        await engine.seed(intent)

        original = fetcher.fetch

        async def counting_fetch(url, *, user_agent):
            nonlocal fetches
            result = await original(url, user_agent=user_agent)
            fetches += 1
            return result

        fetcher.fetch = counting_fetch
        outcome = await engine.run(intent)
        assert outcome.stats.pages_fetched == 1

    async def test_coercion_failures_null_the_field(self, ports, fetcher):
        fetcher.add(f"{SITE}/", PRODUCT.format(name="Weird", price="call us", links=""))
        intent = make_intent(seeds=(f"{SITE}/",))
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)
        assert outcome.stats.records_extracted == 1
        record = ports.records.records[0]
        assert record.fields["title"] == "Weird"
        assert record.fields["price"] is None

    async def test_relative_url_fields_resolve_against_fetched_page(self, ports, fetcher):
        from pulsecrawl.core.model import FieldSpec

        url = f"{SITE}/articles/story"
        fetcher.add(
            url,
            '<h1>Story</h1><link rel="canonical" href="../canonical">',
        )
        intent = make_intent(
            seeds=(url,),
            fields=(
                FieldSpec("fld_title", "title", "string"),
                FieldSpec("fld_url", "canonical", "url"),
            ),
            mappings={
                "fld_title": "h1",
                "fld_url": "link[rel=canonical]@href",
            },
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        await engine.run(intent)
        [record] = ports.records.records
        assert record.fields["canonical"] == f"{SITE}/canonical"

    async def test_all_null_records_are_dropped(self, ports, fetcher):
        fetcher.add(f"{SITE}/", "<html><body><div class='price'>call us</div></body></html>")
        intent = make_intent(seeds=(f"{SITE}/",), mappings={"fld_price": ".price"})
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)
        assert outcome.stats.records_extracted == 0

    async def test_invalid_seeds_are_ignored(self, ports):
        intent = make_intent(seeds=("not a url", "mailto:x@y.z"))
        engine = CrawlEngine(ports)
        assert await engine.seed(intent) == 0
        outcome = await engine.run(intent)
        assert isinstance(outcome, Completed)
        assert outcome.stats.pages_fetched == 0


class TestTemplateStacks:
    """Multiple templates per job: first match wins, later ones enrich."""

    async def test_fallback_template_matches_when_primary_does_not(self, ports):
        from pulsecrawl.core.model import TemplateSpec

        ports.fetcher.add("https://shop.example/", "<html><h2>Only H2</h2></html>")
        intent = make_intent(
            mappings={"fld_title": "h1"},
            extra_templates=(
                TemplateSpec(
                    template_id="tmpl_fallback",
                    engine="css",
                    mappings=TemplateSpec.normalize_mappings({"fld_title": "h2"}),
                ),
            ),
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        await engine.run(intent)
        [record] = ports.records.records
        assert record.fields["title"] == "Only H2"
        assert record.template_id == "tmpl_fallback"

    async def test_later_single_record_template_enriches_missing_fields(self, ports):
        from pulsecrawl.core.model import TemplateSpec

        ports.fetcher.add(
            "https://shop.example/",
            "<html><h1>Base</h1><span class='price'>7</span>"
            "<meta property='og:title' content='OG'></html>",
        )
        intent = make_intent(
            mappings={"fld_title": "h1"},  # primary matches title only
            extra_templates=(
                TemplateSpec(
                    template_id="tmpl_enrich",
                    engine="css",
                    mappings=TemplateSpec.normalize_mappings(
                        {"fld_title": "meta[property='og:title']@content", "fld_price": ".price"}
                    ),
                ),
            ),
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        await engine.run(intent)
        [record] = ports.records.records
        # primary keeps its title; the stack fills the field it lacked
        assert record.fields["title"] == "Base"
        assert record.fields["price"] == 7.0
        assert record.template_id == "tmpl_test"

    async def test_scopes_prevent_cross_domain_literals(self, ports):
        from pulsecrawl.core.model import FieldSpec, TemplateScope, TemplateSpec

        ports.fetcher.add("https://one.example/", "<h1>One</h1>")
        ports.fetcher.add("https://two.example/", "<h1>Two</h1>")
        intent = make_intent(
            seeds=("https://one.example/", "https://two.example/"),
            fields=(
                FieldSpec("fld_title", "title", "string"),
                FieldSpec("fld_city", "city", "string"),
            ),
            mappings={"fld_title": "h1", "fld_city": "literal:One City"},
            primary_scope=TemplateScope(hosts=("one.example",)),
            extra_templates=(
                TemplateSpec(
                    template_id="tmpl_two",
                    engine="css",
                    mappings=TemplateSpec.normalize_mappings(
                        {"fld_title": "h1", "fld_city": "literal:Two City"}
                    ),
                    scope=TemplateScope(hosts=("two.example",)),
                ),
            ),
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        await engine.run(intent)

        by_title = {record.fields["title"]: record for record in ports.records.records}
        assert by_title["One"].fields["city"] == "One City"
        assert by_title["Two"].fields["city"] == "Two City"
        assert by_title["One"].template_id == "tmpl_test"
        assert by_title["Two"].template_id == "tmpl_two"

    async def test_url_pattern_is_more_specific_than_host_scope(self, ports):
        from pulsecrawl.core.model import TemplateScope, TemplateSpec

        ports.fetcher.add("https://shop.example/jobs/1", "<h1>Host</h1><h2>Path</h2>")
        intent = make_intent(
            seeds=("https://shop.example/jobs/1",),
            mappings={"fld_title": "h1"},
            primary_scope=TemplateScope(hosts=("shop.example",)),
            extra_templates=(
                TemplateSpec(
                    template_id="tmpl_path",
                    engine="css",
                    mappings=TemplateSpec.normalize_mappings({"fld_title": "h2"}),
                    scope=TemplateScope(
                        hosts=("shop.example",),
                        url_patterns=("https://shop.example/jobs/*",),
                    ),
                ),
            ),
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)
        [record] = ports.records.records
        assert record.fields["title"] == "Path"
        assert record.template_id == "tmpl_path"
        assert outcome.stats.template_coverage["shop.example"]["scopedMatches"] == 1

    async def test_longer_matching_url_pattern_wins_regardless_of_declaration_order(self, ports):
        from pulsecrawl.core.model import TemplateScope, TemplateSpec

        ports.fetcher.add("https://shop.example/jobs/engineering/1", "<h1>Broad</h1><h2>Exact</h2>")
        intent = make_intent(
            seeds=("https://shop.example/jobs/engineering/1",),
            mappings={"fld_title": "h1"},
            primary_scope=TemplateScope(
                hosts=("shop.example",),
                url_patterns=("/jobs/*",),
            ),
            extra_templates=(
                TemplateSpec(
                    template_id="tmpl_engineering",
                    engine="css",
                    mappings=TemplateSpec.normalize_mappings({"fld_title": "h2"}),
                    scope=TemplateScope(
                        hosts=("shop.example",),
                        url_patterns=("/jobs/engineering/*",),
                    ),
                ),
            ),
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        await engine.run(intent)
        [record] = ports.records.records
        assert record.fields["title"] == "Exact"
        assert record.template_id == "tmpl_engineering"

    async def test_system_templates_run_only_after_the_authored_stack_misses(self, ports):
        from pulsecrawl.core.model import TemplateSpec

        ports.fetcher.add(
            "https://shop.example/",
            '<meta property="og:title" content="System"><span class="price">9</span>',
        )
        system = TemplateSpec(
            template_id="tmpl_sys_meta_page",
            engine="meta",
            mappings=TemplateSpec.normalize_mappings({"fld_title": "og:title"}),
            origin="system",
        )
        intent = make_intent(mappings={"fld_title": "h1"}, system_templates=(system,))
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)

        [record] = ports.records.records
        assert record.fields["title"] == "System"
        assert record.template_id == "tmpl_sys_meta_page"
        assert record.template_origin == "system"
        assert record.match_tier == "system_fallback"
        coverage = outcome.stats.template_coverage["shop.example"]
        assert coverage["systemFallbackMatches"] == 1
        assert coverage["needsTemplate"] is True

    async def test_system_template_does_not_enrich_an_authored_match(self, ports):
        from pulsecrawl.core.model import TemplateSpec

        ports.fetcher.add(
            "https://shop.example/",
            '<h1>Authored</h1><meta property="product:price:amount" content="99">',
        )
        system = TemplateSpec(
            template_id="tmpl_sys",
            engine="meta",
            mappings=TemplateSpec.normalize_mappings({"fld_price": "product:price:amount"}),
            origin="system",
        )
        intent = make_intent(mappings={"fld_title": "h1"}, system_templates=(system,))
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)

        [record] = ports.records.records
        assert record.fields["title"] == "Authored"
        assert record.fields["price"] is None
        assert record.match_tier == "stack_fallback"
        assert outcome.stats.template_coverage["shop.example"]["needsTemplate"] is False

    async def test_scoped_system_template_cannot_match_another_host(self, ports):
        from pulsecrawl.core.model import TemplateScope, TemplateSpec

        ports.fetcher.add(
            "https://shop.example/",
            '<meta property="og:title" content="Must not leak">',
        )
        system = TemplateSpec(
            template_id="tmpl_scoped_system",
            engine="meta",
            mappings=TemplateSpec.normalize_mappings({"fld_title": "og:title"}),
            scope=TemplateScope(hosts=("other.example",)),
            origin="system",
        )
        intent = make_intent(mappings={"fld_title": "h1"}, system_templates=(system,))
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)

        assert ports.records.records == []
        coverage = outcome.stats.template_coverage["shop.example"]
        assert coverage["systemFallbackMatches"] == 0
        assert coverage["unmatchedPages"] == 1

    async def test_unmatched_pages_are_flagged_with_bounded_samples(self, ports):
        ports.fetcher.add("https://shop.example/", "<p>nothing useful</p>")
        intent = make_intent(mappings={"fld_title": "h1"})
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)
        assert ports.records.records == []
        coverage = outcome.stats.template_coverage["shop.example"]
        assert coverage["unmatchedPages"] == 1
        assert coverage["needsTemplate"] is True
        assert coverage["sampleUrls"] == ["https://shop.example/"]

    async def test_discovery_page_fallback_does_not_flag_a_host_with_authored_matches(self, ports):
        from pulsecrawl.core.model import TemplateScope, TemplateSpec

        ports.fetcher.add(
            "https://shop.example/",
            '<meta property="og:title" content="Shop"><a href="/article/1">story</a>',
        )
        ports.fetcher.add("https://shop.example/article/1", "<h1>Authored story</h1>")
        system = TemplateSpec(
            template_id="tmpl_sys_meta_page",
            engine="meta",
            mappings=TemplateSpec.normalize_mappings({"fld_title": "og:title"}),
            origin="system",
        )
        intent = make_intent(
            mappings={"fld_title": "h1"},
            primary_scope=TemplateScope(
                hosts=("shop.example",),
                url_patterns=("/article/*",),
            ),
            system_templates=(system,),
        )
        engine = CrawlEngine(ports)
        await engine.seed(intent)
        outcome = await engine.run(intent)
        coverage = outcome.stats.template_coverage["shop.example"]
        assert coverage["systemFallbackMatches"] == 1
        assert coverage["scopedMatches"] == 1
        assert coverage["needsTemplate"] is False
