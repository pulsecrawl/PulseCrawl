"""Crawl engine shared by PulseCrawl's local and hosted modes."""

from .engine import CrawlEngine, EnginePorts
from .local import crawl, LocalCrawlResult
from .model import (
    Completed,
    CrawlOutcome,
    CrawlStats,
    ExecutionIntent,
    FieldSpec,
    Parked,
    Politeness,
    Record,
    SchemaSpec,
    Scope,
    TemplateScope,
    TemplateSpec,
)

__all__ = [
    "CrawlEngine",
    "EnginePorts",
    "crawl",
    "LocalCrawlResult",
    "Completed",
    "CrawlOutcome",
    "CrawlStats",
    "ExecutionIntent",
    "FieldSpec",
    "Parked",
    "Politeness",
    "Record",
    "SchemaSpec",
    "Scope",
    "TemplateScope",
    "TemplateSpec",
]
