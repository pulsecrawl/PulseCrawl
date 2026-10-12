"""URL normalization, hashing, scoping, and link discovery."""

from __future__ import annotations

import hashlib
from fnmatch import fnmatchcase
import re
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse


_SKIP_SCHEMES = ("mailto:", "javascript:", "tel:", "data:")
_DEFAULT_PORTS = {"http": ":80", "https": ":443"}


def normalize_url(url: str, base: str | None = None) -> str | None:
    """Canonical form: absolute, defragmented, lowercase host, no default port.

    Returns None for anything that is not a fetchable http(s) URL.
    """
    candidate = url.strip()
    if (
        not candidate
        or candidate.startswith(_SKIP_SCHEMES)
        or candidate.startswith("#")
    ):
        return None
    if base:
        candidate = urljoin(base, candidate)
    candidate, _ = urldefrag(candidate)
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    netloc = parsed.netloc.lower()
    default_port = _DEFAULT_PORTS[parsed.scheme]
    if netloc.endswith(default_port):
        netloc = netloc[: -len(default_port)]
    path = parsed.path or "/"
    return urlunparse((parsed.scheme, netloc, path, parsed.params, parsed.query, ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def host_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def origin_of(url: str) -> str:
    """Normalized rate-limit origin, including scheme and any non-default port."""
    normalized = normalize_url(url)
    if normalized is None:
        return ""
    parsed = urlparse(normalized)
    return f"{parsed.scheme}://{parsed.netloc}"


def _site_key(host: str) -> str:
    host = host.lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def same_site(url: str, other_host: str) -> bool:
    """Host equality, treating `www.` as the same site."""
    return _site_key(host_of(url)) == _site_key(other_host)


def host_matches(url: str, pattern: str) -> bool:
    """Match a normalized URL host against an exact or ``*.`` host pattern."""
    actual = _site_key(host_of(url))
    expected = _site_key(pattern.strip())
    if expected.startswith("*."):
        suffix = expected[2:]
        return bool(suffix) and actual.endswith(f".{suffix}")
    return bool(expected) and actual == expected


def template_scope_matches(
    url: str,
    *,
    hosts: tuple[str, ...],
    url_patterns: tuple[str, ...],
) -> bool:
    """Both configured dimensions must match; values within one are ORed."""
    normalized = normalize_url(url)
    if normalized is None:
        return False
    if hosts and not any(host_matches(normalized, host) for host in hosts):
        return False
    path = urlparse(normalized).path or "/"
    if url_patterns and not any(
        fnmatchcase(path if pattern.startswith("/") else normalized, pattern)
        for pattern in url_patterns
    ):
        return False
    return bool(hosts or url_patterns)


def matching_url_pattern_specificity(url: str, patterns: tuple[str, ...]) -> int:
    """Return the strongest matching glob's literal-character count.

    A longer concrete path outranks a broad wildcard. Zero means no URL
    pattern matched. Declaration order remains the tie-breaker in the engine.
    """
    normalized = normalize_url(url)
    if normalized is None:
        return 0
    path = urlparse(normalized).path or "/"
    return max(
        (
            len(re.sub(r"[?*\[\]]", "", pattern))
            for pattern in patterns
            if fnmatchcase(path if pattern.startswith("/") else normalized, pattern)
        ),
        default=0,
    )


def in_scope(
    url: str,
    *,
    seed_hosts: frozenset[str],
    same_domain_only: bool,
    include_patterns: tuple[str, ...],
    exclude_patterns: tuple[str, ...],
) -> bool:
    if same_domain_only and not any(same_site(url, host) for host in seed_hosts):
        return False
    for pattern in exclude_patterns:
        if re.search(pattern, url):
            return False
    if include_patterns and not any(re.search(p, url) for p in include_patterns):
        return False
    return True
