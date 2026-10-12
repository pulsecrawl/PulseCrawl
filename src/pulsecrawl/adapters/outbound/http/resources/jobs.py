"""Hosted-mode client for the PulseCrawl REST API (synchronous)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


from pulsecrawl.adapters.outbound.http.resources.base import _Resource
from pulsecrawl.adapters.outbound.http.constants import *
from pulsecrawl.adapters.outbound.http.scope import _normalise_job_scope


class _Jobs(_Resource):
    def create(
        self,
        name: str,
        *,
        seeds: Sequence[str],
        template_id: str | None = None,
        template_ids: Sequence[str] | None = None,
        template_stack: Sequence[Mapping[str, Any]] | None = None,
        dataset_id: str,
        scope: Mapping | None = None,
        politeness: Mapping | None = None,
    ) -> dict:
        """Create a job with one template or a URL-aware template stack.

        A stack entry accepts ``template_id`` plus optional ``hosts`` and
        ``url_patterns``. Scoped entries run before unscoped entries. Compatible
        system templates are automatic fallbacks when the whole stack misses.
        """
        modes = sum(
            value is not None for value in (template_id, template_ids, template_stack)
        )
        if modes != 1:
            raise ValueError(
                "pass exactly one of template_id, template_ids, or template_stack"
            )
        if template_id is not None and not template_id:
            raise ValueError("template_id must not be empty")
        if template_ids is not None and not template_ids:
            raise ValueError("template_ids must not be empty")
        body: dict[str, Any] = {
            "name": name,
            "seeds": list(seeds),
            "datasetId": dataset_id,
        }
        if template_stack is not None:
            entries = []
            for raw in template_stack:
                template = raw.get("templateId") or raw.get("template_id")
                if not template:
                    raise ValueError("every template_stack entry needs template_id")
                scope_raw = raw.get("scope") or {}
                hosts = raw.get("hosts", scope_raw.get("hosts"))
                patterns = raw.get(
                    "urlPatterns",
                    raw.get(
                        "url_patterns",
                        scope_raw.get("urlPatterns", scope_raw.get("url_patterns")),
                    ),
                )
                entry: dict[str, Any] = {"templateId": str(template)}
                scope_body: dict[str, Any] = {}
                if hosts is not None:
                    scope_body["hosts"] = list(hosts)
                if patterns is not None:
                    scope_body["urlPatterns"] = list(patterns)
                if scope_body:
                    entry["scope"] = scope_body
                entries.append(entry)
            if not entries:
                raise ValueError("template_stack must not be empty")
            body["templateStack"] = entries
        elif template_ids is not None:
            body["templateIds"] = list(template_ids)
        else:
            body["templateId"] = template_id
        if scope is not None:
            body["scope"] = _normalise_job_scope(scope)
        if politeness is not None:
            body["politeness"] = dict(politeness)
        return self._c._request("POST", "/jobs", json=body)

    def list(self) -> list[dict]:
        return self._c._request("GET", "/jobs")["jobs"]

    def get(self, job_id: str) -> dict:
        return self._c._request("GET", f"/jobs/{job_id}")

    def update(
        self,
        job_id: str,
        *,
        name: str | None = None,
        seeds: Sequence[str] | None = None,
        scope: Mapping | None = None,
        politeness: Mapping | None = None,
    ) -> dict:
        """Update mutable job settings, including URL and depth limits."""
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if seeds is not None:
            body["seeds"] = list(seeds)
        if scope is not None:
            body["scope"] = _normalise_job_scope(scope)
        if politeness is not None:
            body["politeness"] = dict(politeness)
        if not body:
            raise ValueError("provide at least one job field to update")
        return self._c._request("PATCH", f"/jobs/{job_id}", json=body)

    def run(self, job_id: str) -> dict:
        """Start an execution of this job."""
        return self._c._request("POST", f"/jobs/{job_id}/executions")

    def archive(self, job_id: str) -> None:
        self._c._request("DELETE", f"/jobs/{job_id}")
