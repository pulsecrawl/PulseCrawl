"""Hosted-mode client for the PulseCrawl REST API (synchronous)."""

from __future__ import annotations

from typing import Any, Mapping


from pulsecrawl.adapters.outbound.http.resources.base import _Resource
from pulsecrawl.adapters.outbound.http.constants import *


class _Templates(_Resource):
    def create(
        self,
        name: str,
        *,
        output_schema_id: str,
        engine: str,
        mappings: Mapping[str, Any],
    ) -> dict:
        return self._c._request(
            "POST",
            "/templates",
            json={
                "name": name,
                "outputSchemaId": output_schema_id,
                "engine": engine,
                "mappings": dict(mappings),
            },
        )

    def list(self, *, origin: str | None = None) -> list[dict]:
        params = {"origin": origin} if origin else None
        return self._c._request("GET", "/templates", params=params)["templates"]

    def get(self, template_id: str) -> dict:
        return self._c._request("GET", f"/templates/{template_id}")

    def clone(self, template_id: str) -> dict:
        return self._c._request("POST", f"/templates/{template_id}:clone")

    def delete(self, template_id: str) -> None:
        self._c._request("DELETE", f"/templates/{template_id}")
