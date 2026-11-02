"""CSS engine: selector chains with optional `@attr` / `::all` suffixes.

`"h1"`                                → text content of the first match
`"meta[property='og:title']@content"` → attribute value of the first match
`"div.article-body p::all"`           → text of ALL matches, joined (body text)
`"literal:Chihuahua"`                 → the literal value (constant fallback)
Fallback chains try each expression until one yields a value.
Produces at most one record per page.
"""

from __future__ import annotations

from typing import Mapping

from selectolax.lexbor import LexborHTMLParser as HTMLParser

LITERAL_PREFIX = "literal:"
ALL_SUFFIX = "::all"


def _select_one(tree: HTMLParser, expression: str) -> str | None:
    expr = expression.strip()
    if expr.startswith(LITERAL_PREFIX):
        value = expr[len(LITERAL_PREFIX) :].strip()
        return value or None
    attr = None
    if "@" in expr:
        expr, _, attr = expr.rpartition("@")
        expr = expr.strip()
        attr = attr.strip()
    join_all = expr.endswith(ALL_SUFFIX)
    if join_all:
        expr = expr[: -len(ALL_SUFFIX)].strip()
    if not expr:
        return None
    nodes = (
        tree.css(expr)
        if join_all
        else [n for n in [tree.css_first(expr)] if n is not None]
    )
    values: list[str] = []
    for node in nodes:
        if attr:
            value = node.attributes.get(attr)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
        else:
            text = node.text(strip=True)
            if text:
                values.append(text)
        if values and not join_all:
            break
    if not values:
        return None
    return "\n\n".join(values) if join_all else values[0]


def extract_css(
    html: str, mappings: Mapping[str, tuple[str, ...]]
) -> list[dict[str, str]]:
    tree = HTMLParser(html)
    record: dict[str, str] = {}
    for field_id, chain in mappings.items():
        for expression in chain:
            value = _select_one(tree, expression)
            if value is not None:
                record[field_id] = value
                break
    return [record] if record else []
