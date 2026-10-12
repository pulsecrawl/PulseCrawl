"""Local mode: crawl on this machine, no account, no cloud.

The exact engine the hosted workers run, exposed through a
synchronous call. Results come back as plain dicts (Parquet datasets are a
hosted-product feature).
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping, Sequence

from pulsecrawl.adapters.inbound.python.ephemeral import crawl as _crawl
from pulsecrawl.adapters.inbound.python.ephemeral import LocalCrawlResult


def crawl(
    seeds: Sequence[str],
    *,
    engine: str | None = None,
    mappings: Mapping[str, Any] | None = None,
    templates: Sequence[Mapping[str, Any]] | None = None,
    system_templates: Sequence[Mapping[str, Any]] | None = None,
    fields: Sequence[Mapping[str, str]],
    dataset: str | None = None,
    scope: Mapping[str, Any] | None = None,
    politeness: Mapping[str, Any] | None = None,
    store_raw_pages: bool = False,
    allow_private_networks: bool = False,
    collect_records: bool = True,
    fetcher=None,
) -> "LocalResult":
    """Crawl synchronously and return typed records.

    Pass either one legacy ``engine`` + ``mappings`` pair or an ordered
    ``templates`` stack. Stack entries accept ``template_id``, ``hosts``, and
    ``url_patterns`` (or their API camelCase forms). ``system_templates`` are
    attempted only when the complete authored stack produces no values.

    `dataset` is a folder path: results accumulate there run after run, in
    the same layout the hosted product uses,
    `<dataset>/executions/<id>/{pages/, records-*.jsonl, _manifest.json}`.
    Omit it for a purely in-memory crawl.

    >>> result = crawl(
    ...     ["https://example.com/"],
    ...     engine="meta",
    ...     mappings={"fld_title": ["og:title", "<title>"]},
    ...     fields=[{"fieldId": "fld_title", "name": "title", "type": "string"}],
    ... )
    >>> result.records[0]["title"]
    """
    if templates is not None and (engine is not None or mappings is not None):
        raise ValueError("pass either engine+mappings or templates, not both")
    if templates is None and (engine is None or mappings is None):
        raise ValueError("pass either engine+mappings or templates")

    def normalize(
        entries: Sequence[Mapping[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        if entries is None:
            return None
        normalized: list[dict[str, Any]] = []
        for entry in entries:
            nested_scope = entry.get("scope") or {}
            hosts = entry.get("hosts", nested_scope.get("hosts"))
            patterns = entry.get(
                "url_patterns",
                entry.get("urlPatterns", nested_scope.get("urlPatterns")),
            )
            item = {
                "templateId": entry.get("template_id", entry.get("templateId")),
                "engine": entry["engine"],
                "mappings": entry["mappings"],
            }
            if entry.get("origin") is not None:
                item["origin"] = entry["origin"]
            if hosts or patterns:
                item["scope"] = {
                    **({"hosts": list(hosts)} if hosts else {}),
                    **({"urlPatterns": list(patterns)} if patterns else {}),
                }
            normalized.append(item)
        if not normalized:
            raise ValueError("templates must not be empty")
        return normalized

    normalized_templates = normalize(templates)
    normalized_system_templates = normalize(system_templates)
    writer = None
    if dataset is not None:
        from pulsecrawl.adapters.outbound.filesystem.legacy_execution import (
            LocalExecutionWriter,
        )

        writer = LocalExecutionWriter(dataset)
    outcome = asyncio.run(
        _crawl(
            seeds=seeds,
            engine=engine,
            mappings=mappings,
            templates=normalized_templates,
            system_templates=normalized_system_templates,
            fields=fields,
            scope=scope,
            politeness=politeness,
            store_raw_pages=store_raw_pages,
            allow_private_networks=allow_private_networks,
            fetcher=fetcher,
            page_sink=writer,
            record_sink=writer,
            collect_records=collect_records,
        )
    )
    result = LocalResult(outcome)
    if writer is not None:
        writer.finalize(
            stats=result.stats,
            engine=engine,
            mappings=mappings,
            templates=normalized_templates,
            system_templates=normalized_system_templates,
            fields=fields,
        )
        result.dataset_path = str(writer.dataset_path)
        result.execution_id = writer.execution_id
        result.execution_dir = str(writer.execution_dir)
    return result


class LocalResult:
    dataset_path: str | None = None
    execution_id: str | None = None
    execution_dir: str | None = None

    def __init__(self, result: LocalCrawlResult) -> None:
        self._result = result
        self.records: list[dict] = result.to_dicts()

    @property
    def stats(self) -> dict:
        stats = self._result.stats
        return {
            "pagesDiscovered": stats.pages_discovered,
            "urlsAttempted": stats.urls_attempted,
            "pagesFetched": stats.pages_fetched,
            "pagesFailed": stats.pages_failed,
            "transientRetries": stats.transient_retries,
            "recordsExtracted": stats.records_extracted,
            "bytesProcessed": stats.bytes_processed,
            "robotsChecks": stats.robots_checks,
            "robotsCacheHits": stats.robots_cache_hits,
            "robotsFetches": stats.robots_fetches,
            "robotsFetchFailures": stats.robots_fetch_failures,
            "robotsBlocked": stats.robots_blocked,
            "rateLimitDeferrals": stats.rate_limit_deferrals,
            "rateLimitWaitSeconds": stats.rate_limit_wait_seconds,
            "rateLimitQueueDeferrals": stats.rate_limit_queue_deferrals,
            "rateLimitQueueWaitSeconds": stats.rate_limit_queue_wait_seconds,
            "templateCoverage": stats.template_coverage,
        }

    def sql(self, query, *, row_cap=10_000, timeout_s=30.0):
        from pulsecrawl.adapters.outbound.duckdb.local_result import LocalResultQuery

        return LocalResultQuery(self).query(query, row_cap=row_cap, timeout_s=timeout_s)

    def to_jsonl(self, path: str) -> int:
        """Write records to a JSONL file; returns the row count."""
        import json

        with open(path, "w", encoding="utf-8") as handle:
            for record in self.records:
                handle.write(json.dumps(record) + "\n")
        return len(self.records)
