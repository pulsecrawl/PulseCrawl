"""Hosted-mode client for the PulseCrawl REST API (synchronous)."""

from __future__ import annotations

from typing import Mapping


def _normalise_job_scope(scope: Mapping | None) -> dict | None:
    if scope is None:
        return None
    aliases = {
        "same_domain_only": "sameDomainOnly",
        "max_depth": "maxDepth",
        "max_urls_per_execution": "maxUrlsPerExecution",
        "max_urls_total": "maxUrlsTotal",
        "max_pages": "maxUrlsPerExecution",
        "include_patterns": "includePatterns",
        "exclude_patterns": "excludePatterns",
    }
    normalized = {
        aliases.get(str(key), str(key)): value for key, value in scope.items()
    }
    legacy = normalized.pop("maxPages", None)
    if legacy is not None:
        if (
            "maxUrlsPerExecution" in normalized
            and normalized["maxUrlsPerExecution"] != legacy
        ):
            raise ValueError("maxPages and maxUrlsPerExecution must match")
        normalized["maxUrlsPerExecution"] = legacy
    return normalized
