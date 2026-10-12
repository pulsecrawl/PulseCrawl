"""Extraction engines: HTML in, raw field strings out.

Each engine returns a list of raw records: `{field_id: raw_string}`: one
per entity found on the page (a listing page can yield many). Type coercion
happens in the engine-independent layer above.
"""

from __future__ import annotations

from typing import Callable, Mapping

from pulsecrawl.domain.crawling.model import EngineName
from .css import extract_css
from .jsonld import extract_jsonld
from .meta import extract_meta

RawRecord = dict[str, str]
ExtractFn = Callable[[str, Mapping[str, tuple[str, ...]]], list[RawRecord]]

_ENGINES: dict[EngineName, ExtractFn] = {
    "css": extract_css,
    "jsonld": extract_jsonld,
    "meta": extract_meta,
}


def get_engine(name: EngineName) -> ExtractFn:
    try:
        return _ENGINES[name]
    except KeyError:
        raise ValueError(f"unknown extraction engine: {name}") from None


class HtmlExtractorRegistry:
    """Select the configured stateless HTML extraction strategy."""

    def get_engine(self, name):
        return get_engine(name)
