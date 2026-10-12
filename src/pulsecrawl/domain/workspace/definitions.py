"""Portable definition normalization and identifier validation."""

from __future__ import annotations
import re
import secrets
import math
from typing import Any, Mapping, Sequence
from pulsecrawl.domain.crawling.model import DEFAULT_USER_AGENT

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,255}$")


def _identifier(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(10)}"


def _safe_identifier(value: str, kind: str = "identifier") -> str:
    if not _SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(
            f"{kind} must be 1-256 safe characters: letters, digits, _, ., or -"
        )
    return value


def _scope(value: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(value or {})
    aliases = {
        "same_domain_only": "sameDomainOnly",
        "max_depth": "maxDepth",
        "max_urls_per_execution": "maxUrlsPerExecution",
        "max_urls_total": "maxUrlsTotal",
        "include_patterns": "includePatterns",
        "exclude_patterns": "excludePatterns",
    }
    normalized = {aliases.get(str(key), str(key)): item for key, item in raw.items()}
    result = {
        "sameDomainOnly": bool(normalized.get("sameDomainOnly", True)),
        "maxDepth": int(normalized.get("maxDepth", 3)),
        "maxUrlsPerExecution": int(normalized.get("maxUrlsPerExecution", 1_000)),
        "maxUrlsTotal": int(normalized.get("maxUrlsTotal", 1_000_000)),
        "includePatterns": list(normalized.get("includePatterns") or ()),
        "excludePatterns": list(normalized.get("excludePatterns") or ()),
    }
    if not 0 <= result["maxDepth"] <= 100:
        raise ValueError("maxDepth must be between 0 and 100")
    if not 1 <= result["maxUrlsPerExecution"] <= 1_000_000:
        raise ValueError("maxUrlsPerExecution must be between 1 and 1000000")
    if not result["maxUrlsPerExecution"] <= result["maxUrlsTotal"] <= 10_000_000:
        raise ValueError(
            "maxUrlsTotal must be between maxUrlsPerExecution and 10000000"
        )
    patterns = result["includePatterns"] + result["excludePatterns"]
    if len(patterns) > 2_000 or any(len(str(pattern)) > 2_048 for pattern in patterns):
        raise ValueError("scope supports at most 2000 URL patterns of 2048 characters")
    return result


def _politeness(value: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(value or {})
    aliases = {
        "respect_robots_txt": "respectRobotsTxt",
        "requests_per_second": "requestsPerSecond",
        "organization_requests_per_second": "organizationRequestsPerSecond",
        "user_agent": "userAgent",
    }
    normalized = {aliases.get(str(key), str(key)): item for key, item in raw.items()}
    request_rate = float(normalized.get("requestsPerSecond", 1.0))
    organization_rate = float(
        normalized.get("organizationRequestsPerSecond", request_rate)
    )
    if any(
        not math.isfinite(rate) or not 0 < rate <= 1_000
        for rate in (request_rate, organization_rate)
    ):
        raise ValueError("request rates must be finite and between 0 and 1000")
    user_agent = str(normalized.get("userAgent") or DEFAULT_USER_AGENT)
    if not user_agent.strip() or len(user_agent) > 512:
        raise ValueError("userAgent must contain between 1 and 512 characters")
    return {
        "respectRobotsTxt": bool(normalized.get("respectRobotsTxt", True)),
        "requestsPerSecond": request_rate,
        "organizationRequestsPerSecond": organization_rate,
        "userAgent": user_agent,
    }


def _templates(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not entries:
        raise ValueError("at least one template is required")
    if len(entries) > 100:
        raise ValueError("at most 100 templates are supported")
    result: list[dict[str, Any]] = []
    for raw in entries:
        if raw.get("engine") not in ("css", "jsonld", "meta"):
            raise ValueError("unsupported template engine")
        nested = raw.get("scope") or {}
        hosts = raw.get("hosts", nested.get("hosts")) or ()
        patterns = (
            raw.get("url_patterns", raw.get("urlPatterns", nested.get("urlPatterns")))
            or ()
        )
        mappings = dict(raw["mappings"])
        if not mappings or len(mappings) > 1_000:
            raise ValueError("a template needs between 1 and 1000 field mappings")
        for expression in mappings.values():
            values = (
                expression if isinstance(expression, (list, tuple)) else [expression]
            )
            if (
                not values
                or len(values) > 100
                or any(not str(value) or len(str(value)) > 4_096 for value in values)
            ):
                raise ValueError(
                    "mapping fallback chains need 1-100 expressions up to 4096 characters"
                )
        if len(hosts) + len(patterns) > 2_000:
            raise ValueError("template scope supports at most 2000 hosts and patterns")
        item: dict[str, Any] = {
            "templateId": str(
                raw.get("template_id") or raw.get("templateId") or _identifier("tmpl")
            ),
            "engine": raw["engine"],
            "mappings": {
                str(key): list(value) if isinstance(value, (list, tuple)) else [value]
                for key, value in mappings.items()
            },
            "origin": raw.get("origin", "org"),
        }
        if hosts or patterns:
            item["scope"] = {
                **({"hosts": list(hosts)} if hosts else {}),
                **({"urlPatterns": list(patterns)} if patterns else {}),
            }
        result.append(item)
    return result
