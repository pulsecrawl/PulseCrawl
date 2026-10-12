"""Hosted-mode client for the PulseCrawl REST API (synchronous)."""

from __future__ import annotations

from typing import Sequence


from pulsecrawl.adapters.outbound.http.resources.base import _Resource
from pulsecrawl.adapters.outbound.http.constants import *


class _Schemas(_Resource):
    def create(self, name: str, field_ids: Sequence[str]) -> dict:
        return self._c._request(
            "POST", "/schemas", json={"name": name, "fieldIds": list(field_ids)}
        )

    def list(self, *, origin: str | None = None) -> list[dict]:
        params = {"origin": origin} if origin else None
        return self._c._request("GET", "/schemas", params=params)["schemas"]

    def get(self, schema_id: str) -> dict:
        return self._c._request("GET", f"/schemas/{schema_id}")

    def clone(self, schema_id: str) -> dict:
        return self._c._request("POST", f"/schemas/{schema_id}:clone")
