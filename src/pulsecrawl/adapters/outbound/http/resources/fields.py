"""Hosted-mode client for the PulseCrawl REST API (synchronous)."""

from __future__ import annotations

from typing import Any


from pulsecrawl.adapters.outbound.http.resources.base import _Resource
from pulsecrawl.adapters.outbound.http.constants import *


class _Fields(_Resource):
    def create(self, name: str, type: str, *, description: str | None = None) -> dict:
        body: dict[str, Any] = {"name": name, "type": type}
        if description is not None:
            body["description"] = description
        return self._c._request("POST", "/fields", json=body)

    def list(self, *, origin: str | None = None) -> list[dict]:
        params = {"origin": origin} if origin else None
        return self._c._request("GET", "/fields", params=params)["fields"]

    def get(self, field_id: str) -> dict:
        return self._c._request("GET", f"/fields/{field_id}")
