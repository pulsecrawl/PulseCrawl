"""Deterministic authoring validation using injected extraction strategies."""

from __future__ import annotations
from typing import Any, Mapping, Sequence
from pulsecrawl.domain.templates.authoring import RepresentativePage
from pulsecrawl.domain.templates.coercion import CoercionError, coerce
from pulsecrawl.domain.crawling.model import TemplateSpec, TemplateScope
from pulsecrawl.domain.crawling.urls import normalize_url
from pulsecrawl.application.templates.resolution import TemplateResolver


def _template_spec(
    value: Mapping[str, Any], index: int, *, origin: str = "org"
) -> TemplateSpec:
    nested = value.get("scope") or {}
    hosts = value.get("hosts", nested.get("hosts")) or ()
    patterns = (
        value.get("urlPatterns", value.get("url_patterns", nested.get("urlPatterns")))
        or ()
    )
    scope = TemplateScope(tuple(hosts), tuple(patterns)) if hosts or patterns else None
    return TemplateSpec(
        template_id=str(
            value.get("templateId") or value.get("template_id") or f"draft-{index}"
        ),
        engine=value["engine"],
        mappings=TemplateSpec.normalize_mappings(value["mappings"]),
        scope=scope,
        origin="system" if origin == "system" else "org",
    )


def _page_resolution(
    page: RepresentativePage,
    authored_values: Sequence[Mapping[str, Any]],
    system_values: Sequence[Mapping[str, Any]],
    registry,
) -> dict[str, Any]:
    authored = [
        (_template_spec(item, i), registry.get_engine(item["engine"]))
        for i, item in enumerate(authored_values)
    ]
    systems = [
        (_template_spec(item, i, origin="system"), registry.get_engine(item["engine"]))
        for i, item in enumerate(system_values)
    ]
    resolution = TemplateResolver().resolve(
        authored, systems, page.body, page.effective_url
    )
    applicable, matched, selected = (
        resolution.applicable,
        resolution.authored_matches,
        resolution.matched,
    )
    tier = resolution.match_tier
    records, provenance, conflicts = (
        resolution.records,
        resolution.field_provenance,
        resolution.conflicts,
    )

    outside_scope: list[str] = []
    applicable_ids = {template.template_id for template, _extract in applicable}
    for template, extract in authored:
        if template.template_id in applicable_ids or template.scope is None:
            continue
        if extract(page.body, template.mappings):
            outside_scope.append(template.template_id)

    return {
        "url": page.effective_url,
        "role": page.role,
        "matchTier": tier,
        "winnerTemplateId": selected[0][0].template_id if selected else None,
        "matchedTemplateIds": [template.template_id for template, _rows in selected],
        "applicableAuthoredMatchIds": [
            template.template_id for template, _rows in matched
        ],
        "outsideScopeMatches": outside_scope,
        "records": records,
        "fieldProvenance": provenance,
        "entityCount": len(records),
        "multiEntity": len(records) > 1,
        "ambiguous": bool(conflicts),
        "conflictingFieldValues": conflicts,
        "bodyTruncated": page.body_truncated,
    }


def validate_template_stack(
    templates: Sequence[Mapping[str, Any]],
    pages: Sequence[RepresentativePage | Mapping[str, Any]],
    *,
    system_templates: Sequence[Mapping[str, Any]] = (),
    required_field_ids: Sequence[str] = (),
    field_types: Mapping[str, str] | None = None,
    registry,
    id_factory,
) -> dict[str, Any]:
    """Run deterministic positive, negative, scope, and provenance checks."""
    normalized_pages = [RepresentativePage.from_value(page) for page in pages]
    if not normalized_pages:
        raise ValueError("validation requires at least one representative page")
    if any(page.role not in ("positive", "negative") for page in normalized_pages):
        raise ValueError("representative page role must be positive or negative")
    if any(normalize_url(page.effective_url) is None for page in normalized_pages):
        raise ValueError("representative page URLs must be absolute HTTP(S) URLs")
    if any(page.status < 100 or page.status > 599 for page in normalized_pages):
        raise ValueError("representative page status must be an HTTP status")
    if any(
        not 200 <= page.status < 300
        for page in normalized_pages
        if page.role == "positive"
    ):
        raise ValueError(
            "positive representative pages must have a successful HTTP status"
        )
    results = [
        _page_resolution(page, templates, system_templates, registry)
        for page in normalized_pages
    ]
    positives = [item for item in results if item["role"] == "positive"]
    negatives = [item for item in results if item["role"] == "negative"]
    missing: dict[str, list[str]] = {}
    missing_by_page: list[dict[str, Any]] = []
    for item in positives:
        absent = (
            sorted(
                set().union(
                    *(
                        set(required_field_ids) - set(record)
                        for record in item["records"]
                    )
                )
            )
            if item["records"]
            else sorted(set(required_field_ids))
        )
        if absent:
            missing[item["url"]] = sorted(
                set(missing.get(item["url"], ())) | set(absent)
            )
            missing_by_page.append({"url": item["url"], "missingFieldIds": absent})
    authored_positive_matches = sum(
        item["matchTier"] in ("scoped", "stack_fallback") for item in positives
    )
    negative_matches = [
        item["url"] for item in negatives if item["matchTier"] is not None
    ]
    contamination = [
        {"url": item["url"], "templateIds": item["outsideScopeMatches"]}
        for item in results
        if item["outsideScopeMatches"]
    ]
    coercion_failures: list[dict[str, str]] = []
    for item in results:
        coerced_records: list[dict[str, Any]] = []
        for record in item["records"]:
            coerced: dict[str, Any] = {}
            for field_id, value in record.items():
                field_type = (field_types or {}).get(field_id)
                if field_type is None:
                    coerced[field_id] = value
                    continue
                try:
                    coerced[field_id] = coerce(value, field_type, base_url=item["url"])
                except CoercionError:
                    coerced[field_id] = None
                    coercion_failures.append({"url": item["url"], "fieldId": field_id})
            coerced_records.append(coerced)
        item["coercedRecords"] = coerced_records
    required_coercion_failure = any(
        item["fieldId"] in required_field_ids for item in coercion_failures
    )
    truncated = any(item["bodyTruncated"] for item in results)
    oracle_mismatches: list[dict[str, Any]] = []
    oracle_unexpected: list[dict[str, Any]] = []
    for page, item in zip(normalized_pages, results):
        if page.role != "positive":
            continue
        expected = page.expected_records
        unmatched_actual = list(range(len(item["coercedRecords"])))
        for expected_record in expected:
            matched_index = next(
                (
                    index
                    for index in unmatched_actual
                    if all(
                        item["coercedRecords"][index].get(key) == value
                        for key, value in expected_record.items()
                    )
                ),
                None,
            )
            if matched_index is None:
                oracle_mismatches.append(
                    {
                        "url": item["url"],
                        "expectedRecord": dict(expected_record),
                    }
                )
            else:
                unmatched_actual.remove(matched_index)
        if expected:
            oracle_unexpected.extend(
                {
                    "url": item["url"],
                    "record": item["coercedRecords"][index],
                }
                for index in unmatched_actual
            )
    passed = bool(positives) and bool(negatives)
    passed = passed and authored_positive_matches == len(positives)
    passed = passed and not negative_matches and not missing
    passed = passed and not required_coercion_failure and not truncated
    passed = passed and not oracle_mismatches and not oracle_unexpected
    return {
        "validationId": id_factory("validation"),
        "passed": passed,
        "summary": {
            "pages": len(results),
            "positivePages": len(positives),
            "authoredPositiveMatches": authored_positive_matches,
            "negativePages": len(negatives),
            "negativeMatches": len(negative_matches),
            "scopeContainmentSignals": len(contamination),
            "systemFallbackMatches": sum(
                item["matchTier"] == "system_fallback" for item in results
            ),
            "unmatchedPages": sum(item["matchTier"] is None for item in results),
            "ambiguousPages": sum(bool(item["ambiguous"]) for item in results),
            "multiEntityPages": sum(bool(item["multiEntity"]) for item in results),
            "truncatedPages": sum(bool(item["bodyTruncated"]) for item in results),
            "valueOraclePages": sum(
                bool(page.expected_records) for page in normalized_pages
            ),
        },
        "missingRequiredFields": missing,
        "missingRequiredFieldsByPage": missing_by_page,
        "negativeMatchUrls": negative_matches,
        "crossScopeContaminationSignals": contamination,
        "coercionFailures": coercion_failures,
        "oracleMismatches": oracle_mismatches,
        "oracleUnexpectedRecords": oracle_unexpected,
        "pages": results,
    }
