"""Deterministic, model-vendor-neutral template authoring support.

This module deliberately does not call an LLM. It exposes governed page
sampling, machine-readable inspection, deterministic validation, and explicit
approval/promotion so a person or an external agent can author normal
PulseCrawl templates without becoming part of scheduled extraction.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Mapping

from selectolax.lexbor import LexborHTMLParser as HTMLParser


from pulsecrawl.domain.templates.authoring import RepresentativePage, PageInspection


def _json_paths(
    value: Any, prefix: str = "", *, depth: int = 0, maximum_depth: int = 8
) -> set[str]:
    paths: set[str] = set()
    if depth >= maximum_depth:
        return paths
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key.startswith("@"):
                continue
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.add(path)
            paths.update(
                _json_paths(child, path, depth=depth + 1, maximum_depth=maximum_depth)
            )
    elif isinstance(value, list) and value:
        paths.update(
            _json_paths(value[0], prefix, depth=depth + 1, maximum_depth=maximum_depth)
        )
    return paths


def _iter_jsonld_entities(html: str, *, maximum_nodes: int = 5_000):
    tree = HTMLParser(html)
    visited = 0
    for script in tree.css('script[type="application/ld+json"]')[:100]:
        raw = script.text(strip=False)
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack and visited < maximum_nodes:
            node = stack.pop()
            visited += 1
            if isinstance(node, list):
                stack.extend(node[:1_000])
            elif isinstance(node, Mapping):
                graph = node.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph[:1_000])
                elif isinstance(graph, Mapping):
                    stack.append(graph)
                if "@type" in node:
                    yield node
        if visited >= maximum_nodes:
            return


def _safe_class(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{1,48}", value)) and not re.search(
        r"\d{5,}|[a-f0-9]{10,}", value, re.I
    )


def inspect_page(
    page: RepresentativePage | Mapping[str, Any],
    *,
    include_content_samples: bool = False,
    max_body_bytes: int = 5 * 1024 * 1024,
) -> PageInspection:
    """Describe bounded markup without treating page text as instructions."""
    page = RepresentativePage.from_value(page)
    if max_body_bytes <= 0 or len(page.body.encode()) > max_body_bytes:
        raise ValueError("page body exceeds the inspection byte limit")
    tree = HTMLParser(page.body)
    entities: list[dict[str, Any]] = []
    for entity in _iter_jsonld_entities(page.body):
        declared = entity.get("@type")
        types = [declared] if isinstance(declared, str) else list(declared or ())
        entities.append(
            {
                "types": [str(item) for item in types],
                "paths": sorted(_json_paths(entity))[:500],
            }
        )
        if len(entities) >= 100:
            break

    meta: dict[str, str] = {}
    for node in tree.css("meta"):
        key = node.attributes.get("property") or node.attributes.get("name")
        content = node.attributes.get("content")
        if key and isinstance(content, str) and key not in meta:
            meta[str(key)] = content[:500] if include_content_samples else "[present]"
    title = tree.css_first("title")
    if title and title.text(strip=True):
        meta["<title>"] = (
            title.text(strip=True)[:500] if include_content_samples else "[present]"
        )

    counts: Counter[str] = Counter()
    for node in tree.css("*"):
        if node.attributes.get("id") and _safe_class(str(node.attributes["id"])):
            counts[f"#{node.attributes['id']}"] += 1
        for class_name in str(node.attributes.get("class", "")).split():
            if _safe_class(class_name):
                counts[f".{class_name}"] += 1
        if node.tag in ("h1", "h2", "article", "main", "time", "address"):
            counts[str(node.tag)] += 1

    candidates: list[dict[str, Any]] = []
    repeated: list[dict[str, Any]] = []
    for selector, count in sorted(counts.items(), key=lambda item: (item[1], item[0])):
        if count <= 3:
            node = tree.css_first(selector)
            candidates.append(
                {
                    "selector": selector,
                    "count": count,
                    "sample": (
                        node.text(strip=True)[:160]
                        if include_content_samples and node
                        else ""
                    ),
                }
            )
        elif selector.startswith("."):
            repeated.append({"selector": selector, "count": count})

    for tag in ("article", "li", "tr"):
        count = len(tree.css(tag))
        if count > 1:
            repeated.append({"selector": tag, "count": count})

    return PageInspection(
        final_url=page.effective_url,
        status=page.status,
        fetched_at=page.fetched_at,
        body_truncated=page.body_truncated,
        body_bytes=page.body_bytes or len(page.body.encode()),
        jsonld_entities=tuple(entities),
        meta_fields=meta,
        selector_candidates=tuple(candidates[:100]),
        repeated_structures=tuple(
            sorted(repeated, key=lambda item: (-item["count"], item["selector"]))[:50]
        ),
    )
