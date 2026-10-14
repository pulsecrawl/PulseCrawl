"""Domain model: immutable value objects shared by local and hosted mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
from typing import Any, Literal, Mapping

FieldType = Literal["string", "number", "boolean", "datetime", "url"]
EngineName = Literal["css", "jsonld", "meta"]
TemplateOrigin = Literal["org", "system"]
MatchTier = Literal["scoped", "stack_fallback", "system_fallback"]

DEFAULT_USER_AGENT = "PulseCrawlBot/0.1 (+https://github.com/pulsecrawl/PulseCrawl)"


@dataclass(frozen=True)
class FieldSpec:
    field_id: str
    name: str
    type: FieldType

    def __post_init__(self) -> None:
        if (
            not isinstance(self.field_id, str)
            or not self.field_id
            or len(self.field_id) > 256
        ):
            raise ValueError("field_id must contain between 1 and 256 characters")
        if not isinstance(self.name, str) or not self.name or len(self.name) > 256:
            raise ValueError("field name must contain between 1 and 256 characters")
        if self.type not in ("string", "number", "boolean", "datetime", "url"):
            raise ValueError("unsupported field type")


@dataclass(frozen=True)
class SchemaSpec:
    schema_id: str
    fields: tuple[FieldSpec, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_id, str)
            or not self.schema_id
            or len(self.schema_id) > 256
        ):
            raise ValueError("schema_id must contain between 1 and 256 characters")
        if not self.fields or len(self.fields) > 1_000:
            raise ValueError("a schema needs between 1 and 1000 fields")
        identifiers = [field.field_id for field in self.fields]
        names = [field.name.lower() for field in self.fields]
        if len(set(identifiers)) != len(identifiers) or len(set(names)) != len(names):
            raise ValueError("schema field ids and names must be unique")

    def by_id(self, field_id: str) -> FieldSpec | None:
        for spec in self.fields:
            if spec.field_id == field_id:
                return spec
        return None


@dataclass(frozen=True)
class TemplateScope:
    """Optional URL applicability for one entry in a job's template stack.

    Host entries are exact except for a leading ``*.`` wildcard. URL patterns
    are shell-style globs matched against the normalized final URL; patterns
    beginning with ``/`` match only its path.
    """

    hosts: tuple[str, ...] = ()
    url_patterns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        values = self.hosts + self.url_patterns
        if len(values) > 2_000:
            raise ValueError("template scope supports at most 2000 entries")
        if any(
            not isinstance(value, str) or not value or len(value) > 2_048
            for value in values
        ):
            raise ValueError("template scope entries must contain 1-2048 characters")


@dataclass(frozen=True)
class TemplateSpec:
    template_id: str
    engine: EngineName
    # Every field maps to an ordered fallback chain of selector expressions.
    mappings: Mapping[str, tuple[str, ...]]
    scope: TemplateScope | None = None
    origin: TemplateOrigin = "org"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.template_id, str)
            or not self.template_id
            or len(self.template_id) > 256
        ):
            raise ValueError("template_id must contain between 1 and 256 characters")
        if self.engine not in ("css", "jsonld", "meta"):
            raise ValueError("unsupported template engine")
        if self.origin not in ("org", "system"):
            raise ValueError("unsupported template origin")
        if not self.mappings or len(self.mappings) > 1_000:
            raise ValueError("a template needs between 1 and 1000 mappings")
        for field_id, expressions in self.mappings.items():
            if not isinstance(field_id, str) or not field_id or len(field_id) > 256:
                raise ValueError("mapping field ids must contain 1-256 characters")
            if not expressions or len(expressions) > 100:
                raise ValueError(
                    "mapping fallback chains need between 1 and 100 entries"
                )
            if any(
                not isinstance(expression, str)
                or not expression
                or len(expression) > 4_096
                for expression in expressions
            ):
                raise ValueError("mapping expressions must contain 1-4096 characters")

    @staticmethod
    def normalize_mappings(raw: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
        """Accept `str` or `list[str]` per field; store as tuples."""
        normalized: dict[str, tuple[str, ...]] = {}
        for field_id, expr in raw.items():
            if isinstance(expr, str):
                normalized[field_id] = (expr,)
            else:
                normalized[field_id] = tuple(str(e) for e in expr)
        return normalized


@dataclass(frozen=True)
class Scope:
    same_domain_only: bool = True
    max_depth: int = 3
    max_pages: int = 1000
    include_patterns: tuple[str, ...] = ()
    exclude_patterns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_depth, bool)
            or not isinstance(self.max_depth, int)
            or self.max_depth < 0
            or self.max_depth > 100
        ):
            raise ValueError("max_depth must be between 0 and 100")
        if (
            isinstance(self.max_pages, bool)
            or not isinstance(self.max_pages, int)
            or self.max_pages < 1
            or self.max_pages > 1_000_000
        ):
            raise ValueError("max_pages must be between 1 and 1000000")
        if len(self.include_patterns) + len(self.exclude_patterns) > 2_000:
            raise ValueError("scope supports at most 2000 URL patterns")
        if any(
            not isinstance(pattern, str) or len(pattern) > 2_048
            for pattern in self.include_patterns + self.exclude_patterns
        ):
            raise ValueError("URL patterns must not exceed 2048 characters")


@dataclass(frozen=True)
class Politeness:
    respect_robots_txt: bool = True
    requests_per_second: float = 1.0
    # Hosted executions freeze the organization's per-website ceiling here.
    # A job may ask to go slower, never faster.
    organization_requests_per_second: float = 1.0
    user_agent: str = DEFAULT_USER_AGENT

    def __post_init__(self) -> None:
        rates = (self.requests_per_second, self.organization_requests_per_second)
        if any(
            isinstance(rate, bool)
            or not isinstance(rate, (int, float))
            or not math.isfinite(rate)
            or not 0 < rate <= 1_000
            for rate in rates
        ):
            raise ValueError("request rates must be finite and between 0 and 1000")
        if (
            not isinstance(self.user_agent, str)
            or not self.user_agent.strip()
            or len(self.user_agent) > 512
        ):
            raise ValueError("user_agent must contain between 1 and 512 characters")


@dataclass(frozen=True)
class ExecutionIntent:
    """The frozen snapshot the engine executes: identical in local and hosted mode."""

    execution_id: str
    org_id: str
    job_id: str
    seeds: tuple[str, ...]
    dataset_id: str
    # A priority-ordered template stack, all outputting the same schema. The
    # first template that matches a page produces its record(s); later ones
    # only fill fields the earlier match left empty.
    templates: tuple[TemplateSpec, ...]
    schema: SchemaSpec
    # Automatic, compatible system fallbacks. These run only when none of the
    # authored stack entries produces real values.
    system_templates: tuple[TemplateSpec, ...] = ()
    scope: Scope = Scope()
    politeness: Politeness = Politeness()
    store_raw_pages: bool = True

    def __post_init__(self) -> None:
        if not self.templates:
            raise ValueError("an execution needs at least one template")
        if not self.seeds or len(self.seeds) > 10_000:
            raise ValueError("an execution needs between 1 and 10000 seeds")
        if len(self.templates) + len(self.system_templates) > 100:
            raise ValueError("an execution supports at most 100 templates")
        if any(
            not isinstance(seed, str) or not seed or len(seed) > 8_192
            for seed in self.seeds
        ):
            raise ValueError("seed URLs must contain 1-8192 characters")
        identifiers = (self.execution_id, self.org_id, self.job_id, self.dataset_id)
        if any(
            not isinstance(value, str) or not value or len(value) > 256
            for value in identifiers
        ):
            raise ValueError("execution identifiers must contain 1-256 characters")

    @property
    def template(self) -> TemplateSpec:
        """The primary (highest-priority) template."""
        return self.templates[0]


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    status: int
    headers: Mapping[str, str]
    body: str | None
    error: str | None
    fetched_at: datetime
    body_truncated: bool = False
    body_bytes: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None and self.status == 200 and self.body is not None


@dataclass(frozen=True)
class PageSnapshot:
    """What gets persisted under executions/{org}/{exec}/pages/{urlHash}.json."""

    url: str
    final_url: str
    status: int
    headers: Mapping[str, str]
    body: str
    depth: int
    fetched_at: datetime
    body_truncated: bool = False
    body_bytes: int = 0


@dataclass(frozen=True)
class RobotsCacheEntry:
    text: str
    fetched_at: float
    fetch_failed: bool = False


@dataclass(frozen=True)
class Record:
    """One extracted, coerced row. Provenance beyond the page is added downstream."""

    fields: Mapping[str, Any]
    source_url: str
    fetched_at: datetime
    # Which template in the stack produced this row (None: single-template runs).
    template_id: str | None = None
    template_origin: TemplateOrigin | None = None
    match_tier: MatchTier | None = None


@dataclass(frozen=True)
class PendingUrl:
    """One admitted URL awaiting processing, including deferred or leased work."""

    url: str
    depth: int
    not_before: float = (
        0.0  # readiness-clock coordinate (epoch when durable); 0 = immediate
    )
    # A distributed rate slot already allocated for this item. The expiry is
    # wall-clock epoch seconds; stale slots are reallocated before HTTP.
    rate_scheduled: bool = False
    rate_slot_expires_at: float = 0.0
    rate_interval_s: float = 0.0
    # Persisted so a process restart cannot reset a server-directed retry loop.
    retry_count: int = 0


@dataclass(frozen=True)
class VisitedRow:
    url_hash: str
    url: str
    status: Literal["queued", "fetched", "failed", "robots_blocked", "skipped"]
    depth: int
    error: str | None = None


@dataclass
class CrawlStats:
    pages_discovered: int = 0
    # Page HTTP requests attempted. This is the safety/budget counter: failed
    # responses consume capacity just like successful responses.
    urls_attempted: int = 0
    pages_fetched: int = 0
    pages_failed: int = 0
    transient_retries: int = 0
    records_extracted: int = 0
    bytes_processed: int = 0
    robots_checks: int = 0
    robots_cache_hits: int = 0
    robots_fetches: int = 0
    robots_fetch_failures: int = 0
    robots_blocked: int = 0
    rate_limit_deferrals: int = 0
    rate_limit_wait_seconds: float = 0.0
    rate_limit_queue_deferrals: int = 0
    rate_limit_queue_wait_seconds: float = 0.0
    template_coverage: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class Completed:
    stats: CrawlStats
    kind: Literal["completed"] = "completed"


@dataclass(frozen=True)
class Parked:
    """Pending URLs exist, but nothing is allowed before `resume_after_s`.

    Hosted mode re-enqueues the execution message with this visibility delay
    and exits (scale-to-zero during politeness waits); local mode just sleeps.
    """

    stats: CrawlStats
    resume_after_s: float
    kind: Literal["parked"] = "parked"


CrawlOutcome = Completed | Parked
