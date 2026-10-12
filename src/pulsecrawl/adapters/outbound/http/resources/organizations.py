"""Hosted-mode client for the PulseCrawl REST API (synchronous)."""

from __future__ import annotations

from typing import Any


from pulsecrawl.adapters.outbound.http.resources.base import _Resource
from pulsecrawl.adapters.outbound.http.constants import *


class _Organizations(_Resource):
    def get(self, org_id: str) -> dict:
        return self._c._request("GET", f"/organizations/{org_id}")

    def update(
        self,
        org_id: str,
        *,
        name: str | None = None,
        requests_per_second_per_website: float | None = None,
    ) -> dict:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if requests_per_second_per_website is not None:
            if requests_per_second_per_website <= 0:
                raise ValueError("requests_per_second_per_website must be positive")
            body["rateLimits"] = {
                "requestsPerSecondPerWebsite": requests_per_second_per_website
            }
        if not body:
            raise ValueError("provide name or requests_per_second_per_website")
        return self._c._request("PATCH", f"/organizations/{org_id}", json=body)
