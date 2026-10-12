"""Compatibility construction of crawl ports with the standard HTML adapters."""

from dataclasses import dataclass, field
from pulsecrawl.application.crawling.engine import (
    CrawlEngine,
    EnginePorts as _EnginePorts,
)
from pulsecrawl.adapters.outbound.html.extraction import HtmlExtractorRegistry
from pulsecrawl.adapters.outbound.html.links import HtmlLinkParser


@dataclass
class EnginePorts(_EnginePorts):
    extractors: object = field(default_factory=HtmlExtractorRegistry)
    links: object = field(default_factory=HtmlLinkParser)
