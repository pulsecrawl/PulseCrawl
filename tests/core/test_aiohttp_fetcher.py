"""Integration tests for the real fetcher against a local aiohttp server."""
import asyncio
import gzip

import pytest
from aiohttp import web

from pulsecrawl.core.adapters.aiohttp_fetcher import AiohttpFetcher, _public_address


@pytest.fixture
async def server():
    hits = {"count": 0, "user_agent": None}

    async def ok(request):
        hits["user_agent"] = request.headers.get("User-Agent")
        return web.Response(text="<h1>hi</h1>", content_type="text/html")

    async def redirect(request):
        raise web.HTTPFound("/ok")

    async def pdf(request):
        return web.Response(body=b"%PDF", content_type="application/pdf")

    async def missing(request):
        raise web.HTTPNotFound()

    async def robots(request):
        return web.Response(text="User-agent: *\nDisallow: /private", content_type="text/plain")

    async def flaky(request):
        hits["count"] += 1
        if hits["count"] < 2:
            raise web.HTTPServiceUnavailable()
        return web.Response(text="<p>recovered</p>", content_type="text/html")

    async def large(request):
        return web.Response(body=b"x" * 32, content_type="text/html")

    async def bad_charset(request):
        return web.Response(
            body=b"<p>still readable</p>",
            headers={"Content-Type": "text/html; charset=not-a-real-charset"},
        )

    async def compressed(request):
        expanded = b"z" * (1024 * 1024)
        return web.Response(
            body=gzip.compress(expanded),
            headers={
                "Content-Type": "text/html",
                "Content-Encoding": "gzip",
            },
        )

    async def slow_body(request):
        response = web.StreamResponse(headers={"Content-Type": "text/html"})
        await response.prepare(request)
        await response.write(b"<p>")
        await asyncio.sleep(0.2)
        await response.write(b"late</p>")
        return response

    async def oversized_header(request):
        response = web.Response(
            text="ok",
            headers={"X-Oversized": "x" * 4096},
            content_type="text/html",
        )
        response.force_close()
        return response

    app = web.Application()
    app.router.add_get("/ok", ok)
    app.router.add_get("/redirect", redirect)
    app.router.add_get("/pdf", pdf)
    app.router.add_get("/missing", missing)
    app.router.add_get("/robots.txt", robots)
    app.router.add_get("/flaky", flaky)
    app.router.add_get("/large", large)
    app.router.add_get("/bad-charset", bad_charset)
    app.router.add_get("/compressed", compressed)
    app.router.add_get("/slow-body", slow_body)
    app.router.add_get("/oversized-header", oversized_header)

    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}", hits
    await runner.cleanup()


class TestAiohttpFetcher:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"timeout_s": 0},
            {"timeout_s": float("nan")},
            {"retries": 0},
            {"dns_cache_ttl_s": -1},
            {"max_backoff_s": float("inf")},
            {"max_body_bytes": 0},
            {"max_header_field_bytes": 0},
        ],
    )
    def test_rejects_invalid_resource_limits(self, kwargs):
        with pytest.raises(ValueError):
            AiohttpFetcher(**kwargs)

    @pytest.mark.parametrize(
        ("address", "allowed"),
        [
            ("8.8.8.8", True),
            ("2001:4860:4860::8888", True),
            ("127.0.0.1", False),
            ("10.0.0.1", False),
            ("169.254.169.254", False),
            ("::1", False),
            ("fc00::1", False),
            ("fe80::1%en0", False),
            ("192.0.2.1", False),
            ("224.0.0.1", False),
            ("239.255.255.250", False),
            ("ff02::1", False),
            ("ff00::", False),
            ("0.0.0.0", False),
            ("::", False),
            ("255.255.255.255", False),
            ("::ffff:127.0.0.1", False),
            ("::ffff:239.255.255.250", False),
            ("::ffff:8.8.8.8", True),
            ("not-an-address", False),
        ],
    )
    def test_public_address_classifier(self, address, allowed):
        assert _public_address(address) is allowed

    def test_safe_mode_refuses_adapter_internal_redirects(self):
        with pytest.raises(ValueError, match="authorize each redirect"):
            AiohttpFetcher(allow_redirects=True)

    async def test_fetches_html_and_sends_user_agent(self, server):
        base, hits = server
        fetcher = AiohttpFetcher(allow_private_networks=True)
        try:
            result = await fetcher.fetch(f"{base}/ok", user_agent="TestBot/1.0")
            assert result.ok and "<h1>hi</h1>" in (result.body or "")
            assert hits["user_agent"] == "TestBot/1.0"
        finally:
            await fetcher.close()

    async def test_follows_redirects_reports_final_url(self, server):
        base, _ = server
        fetcher = AiohttpFetcher(allow_redirects=True, allow_private_networks=True)
        try:
            result = await fetcher.fetch(f"{base}/redirect", user_agent="T")
            assert result.ok and result.final_url.endswith("/ok")
        finally:
            await fetcher.close()

    async def test_can_expose_redirect_for_engine_level_safety_checks(self, server):
        base, _ = server
        fetcher = AiohttpFetcher(allow_redirects=False, allow_private_networks=True)
        try:
            result = await fetcher.fetch(f"{base}/redirect", user_agent="T")
            assert result.status == 302
            assert result.final_url.endswith("/redirect")
            assert result.headers["Location"] == "/ok"
        finally:
            await fetcher.close()

    async def test_redirects_are_safe_by_default(self, server):
        base, _ = server
        fetcher = AiohttpFetcher(allow_private_networks=True)
        try:
            result = await fetcher.fetch(f"{base}/redirect", user_agent="T")
            assert result.status == 302
            assert result.headers["Location"] == "/ok"
        finally:
            await fetcher.close()

    async def test_marks_a_capped_body_as_truncated(self, server):
        base, _ = server
        fetcher = AiohttpFetcher(max_body_bytes=8, allow_private_networks=True)
        try:
            result = await fetcher.fetch(f"{base}/large", user_agent="T")
            assert result.ok
            assert result.body == "x" * 8
            assert result.body_bytes == 8
            assert result.body_truncated is True
        finally:
            await fetcher.close()

    async def test_exactly_capped_body_is_not_reported_as_truncated(self, server):
        base, _ = server
        fetcher = AiohttpFetcher(max_body_bytes=32, allow_private_networks=True)
        try:
            result = await fetcher.fetch(f"{base}/large", user_agent="T")
            assert result.ok
            assert result.body == "x" * 32
            assert result.body_bytes == 32
            assert result.body_truncated is False
        finally:
            await fetcher.close()

    async def test_http_status_is_not_retried_inside_transport_adapter(self, server):
        """The engine must own retries so every attempt passes through its gate."""
        base, hits = server
        fetcher = AiohttpFetcher(
            retries=3,
            max_backoff_s=0,
            allow_private_networks=True,
        )
        try:
            result = await fetcher.fetch(f"{base}/flaky", user_agent="T")
            assert result.status == 503
            assert result.error == "HTTP 503"
            assert hits["count"] == 1
        finally:
            await fetcher.close()

    async def test_unknown_charset_falls_back_to_utf8(self, server):
        base, _ = server
        fetcher = AiohttpFetcher(allow_private_networks=True)
        try:
            result = await fetcher.fetch(f"{base}/bad-charset", user_agent="T")
            assert result.ok and result.body == "<p>still readable</p>"
        finally:
            await fetcher.close()

    async def test_decompressed_body_is_bounded(self, server):
        base, _ = server
        fetcher = AiohttpFetcher(
            max_body_bytes=4096,
            allow_private_networks=True,
        )
        try:
            result = await fetcher.fetch(f"{base}/compressed", user_agent="T")
            assert result.ok
            assert result.body == "z" * 4096
            assert result.body_bytes == 4096
            assert result.body_truncated is True
        finally:
            await fetcher.close()

    async def test_slow_stream_is_bounded_by_total_timeout(self, server):
        base, _ = server
        fetcher = AiohttpFetcher(
            timeout_s=0.05,
            retries=1,
            allow_private_networks=True,
        )
        try:
            result = await fetcher.fetch(f"{base}/slow-body", user_agent="T")
            assert result.status == 0
            assert result.body is None
            assert result.error == "timeout after 0.05s"
        finally:
            await fetcher.close()

    async def test_oversized_response_header_fails_closed(self, server):
        base, _ = server
        fetcher = AiohttpFetcher(
            retries=1,
            timeout_s=0.5,
            max_header_field_bytes=1024,
            allow_private_networks=True,
        )
        try:
            result = await fetcher.fetch(
                f"{base}/oversized-header", user_agent="T"
            )
            assert result.status == 0
            assert result.body is None
            assert result.error
        finally:
            await fetcher.close()

    async def test_truncated_content_length_fails_closed(self):
        async def truncate(_reader, writer):
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/html\r\n"
                b"Content-Length: 100\r\n"
                b"Connection: close\r\n\r\nshort"
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        raw_server = await asyncio.start_server(truncate, "127.0.0.1", 0)
        port = raw_server.sockets[0].getsockname()[1]
        fetcher = AiohttpFetcher(retries=1, allow_private_networks=True)
        try:
            result = await fetcher.fetch(
                f"http://127.0.0.1:{port}/truncated", user_agent="T"
            )
            assert result.status == 0
            assert result.body is None
            assert result.error
        finally:
            await fetcher.close()
            raw_server.close()
            await raw_server.wait_closed()

    async def test_rejects_non_html(self, server):
        base, _ = server
        fetcher = AiohttpFetcher(allow_private_networks=True)
        try:
            result = await fetcher.fetch(f"{base}/pdf", user_agent="T")
            assert not result.ok and "non-HTML" in (result.error or "")
        finally:
            await fetcher.close()

    async def test_dedicated_mode_accepts_plain_text_robots(self, server):
        base, _ = server
        fetcher = AiohttpFetcher(
            accepted_content_types=None, retries=1, allow_private_networks=True
        )
        try:
            result = await fetcher.fetch(f"{base}/robots.txt", user_agent="TestBot/1.0")
            assert result.ok and "Disallow: /private" in (result.body or "")
        finally:
            await fetcher.close()

    async def test_non_200_reports_error(self, server):
        base, _ = server
        fetcher = AiohttpFetcher(allow_private_networks=True)
        try:
            result = await fetcher.fetch(f"{base}/missing", user_agent="T")
            assert result.status == 404 and result.error == "HTTP 404"
        finally:
            await fetcher.close()

    async def test_connection_refused_reports_error(self):
        fetcher = AiohttpFetcher(
            retries=1, timeout_s=2, allow_private_networks=True
        )
        try:
            result = await fetcher.fetch("http://127.0.0.1:1/nope", user_agent="T")
            assert not result.ok and result.status == 0 and result.error
        finally:
            await fetcher.close()

    async def test_blocks_literal_private_address_by_default(self, server):
        base, hits = server
        fetcher = AiohttpFetcher(retries=1)
        try:
            result = await fetcher.fetch(f"{base}/ok", user_agent="T")
            assert result.status == 0
            assert result.error == "blocked non-public network target: 127.0.0.1"
            assert hits["user_agent"] is None
        finally:
            await fetcher.close()

    async def test_blocks_hostname_resolving_to_private_address(self, server):
        base, hits = server
        port = base.rsplit(":", 1)[1]
        fetcher = AiohttpFetcher(retries=1)
        try:
            result = await fetcher.fetch(
                f"http://localhost:{port}/ok", user_agent="T"
            )
            assert result.status == 0
            assert "blocked non-public network target" in (result.error or "")
            assert hits["user_agent"] is None
        finally:
            await fetcher.close()
