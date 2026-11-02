"""Translate the v1 wire contract into typed domain objects."""

from __future__ import annotations
from typing import Any, Mapping
from pulsecrawl.domain.crawling.model import (
    DEFAULT_USER_AGENT,
    ExecutionIntent,
    TemplateSpec,
    TemplateScope,
    SchemaSpec,
    FieldSpec,
    Scope,
    Politeness,
)


class IntentMapper:
    @staticmethod
    def from_message_intent(
        *,
        execution_id: str,
        org_id: str,
        job_id: str,
        intent: Mapping[str, Any],
    ) -> "ExecutionIntent":
        """Build from the contracts/messages/v1 CrawlTaskMessage `intent` payload."""
        raw_templates = (
            intent.get("templateStack")
            or intent.get("templates")
            or [intent["template"]]
        )
        raw_system_templates = intent.get("systemTemplates") or ()
        schema = intent["schema"]
        scope = intent.get("scope") or {}
        politeness = intent.get("politeness") or {}
        return ExecutionIntent(
            execution_id=execution_id,
            org_id=org_id,
            job_id=job_id,
            seeds=tuple(intent["seeds"]),
            dataset_id=intent["datasetId"],
            templates=tuple(
                TemplateSpec(
                    template_id=t["templateId"],
                    engine=t["engine"],
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
                for t in raw_templates
            ),
            system_templates=tuple(
                TemplateSpec(
                    template_id=t["templateId"],
                    engine=t["engine"],
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
                    origin="system",
                )
                for t in raw_system_templates
            ),
            schema=SchemaSpec(
                schema_id=schema["schemaId"],
                fields=tuple(
                    FieldSpec(field_id=f["fieldId"], name=f["name"], type=f["type"])
                    for f in schema["fields"]
                ),
            ),
            scope=Scope(
                same_domain_only=scope.get("sameDomainOnly", True),
                max_depth=scope.get("maxDepth", 3),
                max_pages=scope.get("maxUrlsPerExecution", scope.get("maxPages", 1000)),
                include_patterns=tuple(scope.get("includePatterns") or ()),
                exclude_patterns=tuple(scope.get("excludePatterns") or ()),
            ),
            politeness=Politeness(
                respect_robots_txt=politeness.get("respectRobotsTxt", True),
                requests_per_second=politeness.get("requestsPerSecond", 1.0),
                organization_requests_per_second=politeness.get(
                    "organizationRequestsPerSecond", 1.0
                ),
                user_agent=politeness.get("userAgent") or DEFAULT_USER_AGENT,
            ),
            store_raw_pages=bool(intent.get("storeRawPages", True)),
            max_duration_seconds=(
                float(intent["maxDurationSeconds"])
                if intent.get("maxDurationSeconds") is not None
                else None
            ),
        )
