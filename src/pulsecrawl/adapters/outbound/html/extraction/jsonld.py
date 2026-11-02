"""JSON-LD engine: extracts schema.org entities embedded in the page.

Mapping expressions are `Type.path.to.value`: the first segment names the
entity @type (case-insensitive), the rest walks the entity. Lists take the
first element; `@graph` containers and top-level arrays are flattened.
A page with N matching entities yields N records (listing pages work).
"""

from __future__ import annotations

import json
from typing import Any, Iterator, Mapping

from selectolax.lexbor import LexborHTMLParser as HTMLParser


def _iter_entities(html: str) -> Iterator[dict[str, Any]]:
    tree = HTMLParser(html)
    for script in tree.css('script[type="application/ld+json"]'):
        raw = script.text(strip=False)
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack: list[Any] = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                if "@graph" in node:
                    stack.extend(
                        node["@graph"]
                        if isinstance(node["@graph"], list)
                        else [node["@graph"]]
                    )
                if "@type" in node:
                    yield node


def _types_of(entity: dict[str, Any]) -> set[str]:
    declared = entity.get("@type")
    if isinstance(declared, str):
        return {declared.lower()}
    if isinstance(declared, list):
        return {str(t).lower() for t in declared}
    return set()


# schema.org subtypes accepted when a mapping names the parent type. Real
# pages rarely declare the parent: news sites emit NewsArticle, shops emit
# their Product subtypes: an exact match on "Article" would skip them all.
_SUBTYPES: dict[str, frozenset[str]] = {
    "article": frozenset(
        {
            "newsarticle",
            "reportagenewsarticle",
            "analysisnewsarticle",
            "backgroundnewsarticle",
            "opinionnewsarticle",
            "reviewnewsarticle",
            "askpublicnewsarticle",
            "blogposting",
            "liveblogposting",
            "socialmediaposting",
            "scholarlyarticle",
            "techarticle",
            "report",
        }
    ),
    "product": frozenset(
        {"individualproduct", "productmodel", "productgroup", "someproducts", "vehicle"}
    ),
}


def _matches(root: str, entity_types: set[str]) -> bool:
    wanted = root.lower()
    if wanted in entity_types:
        return True
    return not entity_types.isdisjoint(_SUBTYPES.get(wanted, frozenset()))


def _walk(entity: Any, path: list[str]) -> Any:
    current = entity
    for segment in path:
        if isinstance(current, list):
            current = current[0] if current else None
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    if isinstance(current, list):
        # A terminal list of scalars (keywords, sections) joins; else first.
        if current and all(isinstance(v, (str, int, float)) for v in current):
            return ", ".join(str(v) for v in current)
        current = current[0] if current else None
    return current


def extract_jsonld(
    html: str, mappings: Mapping[str, tuple[str, ...]]
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for entity in _iter_entities(html):
        entity_types = _types_of(entity)
        record: dict[str, str] = {}
        for field_id, chain in mappings.items():
            for expression in chain:
                root, _, rest = expression.partition(".")
                if not _matches(root, entity_types):
                    continue
                value = _walk(entity, rest.split(".")) if rest else None
                if value is None or isinstance(value, (dict, list)):
                    continue
                text = str(value).strip()
                if text:
                    record[field_id] = text
                    break
        if record:
            records.append(record)
    return records
