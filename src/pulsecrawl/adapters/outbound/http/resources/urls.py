"""Hosted-mode client for the PulseCrawl REST API (synchronous)."""

from __future__ import annotations


from pulsecrawl.adapters.outbound.http.constants import *


def _url_params(
    cursor: str | None,
    limit: int,
    newness: str,
    host: str | None,
    url_contains: str | None,
) -> dict:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    if newness not in ("all", "new", "repeat"):
        raise ValueError("newness must be all, new, or repeat")
    params: dict[str, str | int] = {"limit": limit, "newness": newness}
    if cursor:
        params["cursor"] = cursor
    if host:
        params["host"] = host
    if url_contains:
        params["urlContains"] = url_contains
    return params
