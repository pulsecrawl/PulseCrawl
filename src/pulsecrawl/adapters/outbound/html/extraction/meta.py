"""Meta engine: OpenGraph / meta-tag extraction.

Mapping expressions are meta keys matched against `property` or `name`
(`og:title`, `description`, …). The special expression `<title>` reads the
document title; `literal:...` yields a constant (annotations like a source
city). Produces at most one record per page: and never a literal-only one.
"""

from __future__ import annotations

from typing import Mapping

from selectolax.lexbor import LexborHTMLParser as HTMLParser

TITLE_EXPRESSION = "<title>"
LITERAL_PREFIX = "literal:"


def extract_meta(
    html: str, mappings: Mapping[str, tuple[str, ...]]
) -> list[dict[str, str]]:
    tree = HTMLParser(html)
    meta_values: dict[str, str] = {}
    for tag in tree.css("meta"):
        key = tag.attributes.get("property") or tag.attributes.get("name")
        content = tag.attributes.get("content")
        if (
            key
            and isinstance(content, str)
            and content.strip()
            and key not in meta_values
        ):
            meta_values[key] = content.strip()

    record: dict[str, str] = {}
    matched_page_content = False
    for field_id, chain in mappings.items():
        for expression in chain:
            expr = expression.strip()
            if expr.startswith(LITERAL_PREFIX):
                value = expr[len(LITERAL_PREFIX) :].strip()
                if value:
                    record[field_id] = value
                    break
            elif expr == TITLE_EXPRESSION:
                node = tree.css_first("title")
                text = node.text(strip=True) if node else ""
                if text:
                    record[field_id] = text
                    matched_page_content = True
                    break
            elif expr in meta_values:
                record[field_id] = meta_values[expr]
                matched_page_content = True
                break
    return [record] if matched_page_content else []
