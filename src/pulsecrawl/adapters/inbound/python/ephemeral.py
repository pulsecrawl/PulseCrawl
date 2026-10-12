"""Local mode: run a crawl on this machine with in-memory adapters.

This is the engine the hosted workers wrap: same behavior, zero cloud.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from pulsecrawl.domain.crawling.model import (
    CrawlOutcome,
    ExecutionIntent,
    FieldSpec,
    Politeness,
    Record,
    SchemaSpec,
    Scope,
    TemplateSpec,
    TemplateScope,
)
from pulsecrawl.application.ports.crawling import Fetcher
from pulsecrawl.bootstrap.ephemeral import run_ephemeral


class LocalCrawlResult:
    def __init__(self, records: list[Record], outcome: CrawlOutcome) -> None:
        self.records = records
        self.outcome = outcome
        self.stats = outcome.stats

    def to_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                **r.fields,
                "_template_id": r.template_id,
                "_template_origin": r.template_origin,
                "_match_tier": r.match_tier,
                "_source_url": r.source_url,
                "_crawled_at": r.fetched_at.isoformat(),
            }
            for r in self.records
        ]


async def crawl(
    *,
    seeds: Sequence[str],
    engine: str | None = None,
    mappings: Mapping[str, Any] | None = None,
    templates: Sequence[Mapping[str, Any]] | None = None,
    system_templates: Sequence[Mapping[str, Any]] | None = None,
    fields: Sequence[Mapping[str, str]],
    scope: Mapping[str, Any] | None = None,
    politeness: Mapping[str, Any] | None = None,
    store_raw_pages: bool = False,
    allow_private_networks: bool = False,
    fetcher: Fetcher | None = None,
    page_sink=None,
    record_sink=None,
    collect_records: bool = True,
) -> LocalCrawlResult:
    """One-call local crawl: seeds + template in, typed records out.

    `page_sink` / `record_sink` let callers persist output (e.g. the SDK's
    filesystem dataset layout). Set ``collect_records=False`` for bounded-memory
    persistent crawls whose rows will be consumed from the record sink.
    """
    scope = scope or {}
    politeness = politeness or {}
    if templates is None:
        if engine is None or mappings is None:
            raise ValueError("pass either engine+mappings or a templates list")
        templates = [{"engine": engine, "mappings": mappings}]
    intent = ExecutionIntent(
        execution_id="local",
        org_id="local",
        job_id="local",
        seeds=tuple(seeds),
        dataset_id="local",
        templates=tuple(
            TemplateSpec(
                template_id=str(t.get("templateId") or f"local-{i}"),
                engine=t["engine"],  # type: ignore[typeddict-item]
                mappings=TemplateSpec.normalize_mappings(t["mappings"]),
                scope=(
                    TemplateScope(
                        hosts=tuple((t.get("scope") or {}).get("hosts") or ()),
                        url_patterns=tuple(
                            (t.get("scope") or {}).get("urlPatterns") or ()
                        ),
                    )
                    if t.get("scope")
                    else None
                ),
                origin=t.get("origin", "org"),
            )
            for i, t in enumerate(templates)
        ),
        schema=SchemaSpec(
            schema_id="local",
            fields=tuple(
                FieldSpec(field_id=f["fieldId"], name=f["name"], type=f["type"])  # type: ignore[arg-type]
                for f in fields
            ),
        ),
        system_templates=tuple(
            TemplateSpec(
                template_id=str(t.get("templateId") or f"system-{i}"),
                engine=t["engine"],  # type: ignore[typeddict-item]
                mappings=TemplateSpec.normalize_mappings(t["mappings"]),
                origin="system",
            )
            for i, t in enumerate(system_templates or ())
        ),
        scope=Scope(
            same_domain_only=scope.get("sameDomainOnly", True),
            max_depth=scope.get("maxDepth", 3),
            max_pages=scope.get("maxUrlsPerExecution", scope.get("maxPages", 100)),
            include_patterns=tuple(scope.get("includePatterns") or ()),
            exclude_patterns=tuple(scope.get("excludePatterns") or ()),
        ),
        politeness=Politeness(
            respect_robots_txt=politeness.get("respectRobotsTxt", True),
            requests_per_second=politeness.get("requestsPerSecond", 1.0),
            organization_requests_per_second=politeness.get(
                "organizationRequestsPerSecond",
                politeness.get("requestsPerSecond", 1.0),
            ),
            user_agent=politeness.get("userAgent") or Politeness().user_agent,
        ),
        store_raw_pages=store_raw_pages,
    )

    records, outcome = await run_ephemeral(
        intent,
        fetcher=fetcher,
        allow_private_networks=allow_private_networks,
        page_sink=page_sink,
        record_sink=record_sink,
        collect_records=collect_records,
    )
    return LocalCrawlResult(records=records, outcome=outcome)
