"""Real HTTP fetcher with DNS caching and bounded representation reads.

Retries apply only to transport failures. HTTP status responses are returned
to the engine after one request so an internal retry cannot bypass the shared
request gate. Redirect following is disabled by default because every target
must pass scope, robots, and origin admission independently.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import ipaddress
import math
import socket
from urllib.parse import urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver

from pulsecrawl.domain.crawling.model import FetchResult

_ACCEPT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.7",
}
_HTML_TYPES = ("text/html", "application/xhtml")
MAX_BODY_BYTES = 5 * 1024 * 1024


def _public_address(value: str) -> bool:
    """Return whether *value* is a globally routable IP address.

    Explicit exclusions supplement ``is_global`` because multicast is marked
    global on some supported Python versions. Untrusted definitions must not
    reach non-unicast or special-purpose destinations.
    """
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            return _public_address(str(address.ipv4_mapped))
        return address.is_global and not any(
            (address.is_multicast, address.is_unspecified, address.is_reserved,
             address.is_loopback, address.is_link_local, address.is_private)
        )
    except ValueError:
        return False


def _literal_address(host: str) -> str | None:
    candidate = host.strip("[]").split("%", 1)[0]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _blocked_target_error(host: str) -> str:
    return f"blocked non-public network target: {host}"


class _SafeResolver(AbstractResolver):
    """Resolve hostnames and reject the entire answer if any address is local.

    The connector uses the returned addresses directly, which binds address
    classification to the connection attempt instead of performing a separate
    preflight lookup vulnerable to DNS rebinding.
    """

    def __init__(self) -> None:
        self._delegate = DefaultResolver()

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ):
        records = await self._delegate.resolve(host, port, family)
        if not records or any(
            not _public_address(record["host"]) for record in records
        ):
            raise OSError(_blocked_target_error(host))
        return records

    async def close(self) -> None:
        await self._delegate.close()


class AiohttpFetcher:
    def __init__(
        self,
        *,
        timeout_s: float = 15.0,
        retries: int = 3,
        dns_cache_ttl_s: int = 300,
        max_backoff_s: float = 30.0,
        accepted_content_types: tuple[str, ...] | None = _HTML_TYPES,
        max_body_bytes: int = MAX_BODY_BYTES,
        max_header_field_bytes: int = 16 * 1024,
        allow_redirects: bool = False,
        allow_private_networks: bool = False,
    ) -> None:
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be finite and positive")
        if isinstance(retries, bool) or not isinstance(retries, int) or retries < 1:
            raise ValueError("retries must be a positive integer")
        if (
            isinstance(dns_cache_ttl_s, bool)
            or not isinstance(dns_cache_ttl_s, int)
            or dns_cache_ttl_s < 0
        ):
            raise ValueError("dns_cache_ttl_s must be a non-negative integer")
        if not math.isfinite(max_backoff_s) or max_backoff_s < 0:
            raise ValueError("max_backoff_s must be finite and non-negative")
        if (
            isinstance(max_body_bytes, bool)
            or not isinstance(max_body_bytes, int)
            or max_body_bytes < 1
        ):
            raise ValueError("max_body_bytes must be a positive integer")
        if (
            isinstance(max_header_field_bytes, bool)
            or not isinstance(max_header_field_bytes, int)
            or max_header_field_bytes < 1
        ):
            raise ValueError("max_header_field_bytes must be a positive integer")
        if allow_redirects and not allow_private_networks:
            raise ValueError(
                "automatic redirects require allow_private_networks=True; "
                "safe crawls must authorize each redirect through the engine"
            )
        self._timeout_s = timeout_s
        self._retries = retries
        self._dns_cache_ttl_s = dns_cache_ttl_s
        self._max_backoff_s = max_backoff_s
        self._accepted_content_types = accepted_content_types
        self._max_body_bytes = max_body_bytes
        self._max_header_field_bytes = max_header_field_bytes
        self._allow_redirects = allow_redirects
        self._allow_private_networks = allow_private_networks
        self._resolver: _SafeResolver | None = None
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._resolver = None if self._allow_private_networks else _SafeResolver()
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(
                    ttl_dns_cache=self._dns_cache_ttl_s,
                    limit_per_host=4,
                    resolver=self._resolver,
                ),
                timeout=aiohttp.ClientTimeout(total=self._timeout_s),
                max_line_size=self._max_header_field_bytes,
                max_field_size=self._max_header_field_bytes,
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        if self._resolver is not None:
            await self._resolver.close()
            self._resolver = None

    async def fetch(self, url: str, *, user_agent: str) -> FetchResult:
        host = urlsplit(url).hostname
        literal = _literal_address(host or "")
        if not self._allow_private_networks and (
            not host or (literal is not None and not _public_address(literal))
        ):
            return FetchResult(
                url=url,
                final_url=url,
                status=0,
                headers={},
                body=None,
                error=_blocked_target_error(host or "invalid-host"),
                fetched_at=datetime.now(timezone.utc),
            )
        headers = {"User-Agent": user_agent, **_ACCEPT_HEADERS}
        last_error = "unreachable"
        for attempt in range(self._retries):
            fetched_at = datetime.now(timezone.utc)
            try:
                session = await self._get_session()
                async with session.get(
                    url,
                    headers=headers,
                    allow_redirects=self._allow_redirects,
                ) as response:
                    if response.status != 200:
                        return FetchResult(
                            url=url,
                            final_url=str(response.url),
                            status=response.status,
                            headers=dict(response.headers),
                            body=None,
                            error=f"HTTP {response.status}",
                            fetched_at=fetched_at,
                        )
                    content_type = response.headers.get("Content-Type", "")
                    if (
                        self._accepted_content_types is not None
                        and content_type
                        and not any(
                            t in content_type.lower()
                            for t in self._accepted_content_types
                        )
                    ):
                        return FetchResult(
                            url=url,
                            final_url=str(response.url),
                            status=response.status,
                            headers=dict(response.headers),
                            body=None,
                            error=f"non-HTML content type: {content_type}",
                            fetched_at=fetched_at,
                        )
                    # StreamReader.read(n) returns only what's buffered (first
                    # chunk of a chunked response): accumulate to the cap.
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        chunks.append(chunk)
                        total += len(chunk)
                        # Read one byte beyond the persistence cap so an exact
                        # cap-sized response is not incorrectly marked short.
                        if total > self._max_body_bytes:
                            break
                    body_bytes = b"".join(chunks)[: self._max_body_bytes]
                    # StreamReader yields decompressed bytes, so this cap also
                    # protects against compressed response expansion.
                    encoding = response.charset or "utf-8"
                    try:
                        body = body_bytes.decode(encoding, errors="replace")
                    except LookupError:
                        body = body_bytes.decode("utf-8", errors="replace")
                    return FetchResult(
                        url=url,
                        final_url=str(response.url),
                        status=response.status,
                        headers=dict(response.headers),
                        body=body,
                        error=None,
                        fetched_at=fetched_at,
                        body_truncated=total > self._max_body_bytes,
                        body_bytes=len(body_bytes),
                    )
            except asyncio.TimeoutError:
                last_error = f"timeout after {self._timeout_s}s"
            except aiohttp.ClientConnectorError as e:
                connector_error = str(e.os_error)
                last_error = (
                    connector_error
                    if "blocked non-public network target" in connector_error
                    else (str(e) or type(e).__name__)
                )
            except aiohttp.ClientError as e:
                last_error = str(e) or type(e).__name__
            if attempt < self._retries - 1:
                await asyncio.sleep(min(2**attempt, self._max_backoff_s))
        return FetchResult(
            url=url,
            final_url=url,
            status=0,
            headers={},
            body=None,
            error=last_error,
            fetched_at=datetime.now(timezone.utc),
        )
