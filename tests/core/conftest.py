from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pulsecrawl.core.adapters.memory import (
    FakeClock,
    MemoryFrontier,
    MemoryHostGate,
    MemoryPageSink,
    MemoryRecordSink,
    MemoryRobotsCache,
    MemoryVisitedStore,
)
from pulsecrawl.core.engine import EnginePorts
from pulsecrawl.core.model import (
    ExecutionIntent,
    FetchResult,
    FieldSpec,
    Politeness,
    SchemaSpec,
    Scope,
    TemplateSpec,
    TemplateScope,
)
from pulsecrawl.core.robots import RobotsService


class FakeFetcher:
    """Serves a url → (status, content_type, body) map; counts calls."""

    def __init__(self, pages: dict[str, tuple[int, str, str]] | None = None) -> None:
        self.pages = pages or {}
        self.calls: list[str] = []

    def add(self, url: str, body: str, status: int = 200, content_type: str = "text/html") -> None:
        self.pages[url] = (status, content_type, body)

    async def fetch(self, url: str, *, user_agent: str) -> FetchResult:
        self.calls.append(url)
        fetched_at = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
        entry = self.pages.get(url)
        if entry is None:
            return FetchResult(
                url=url, final_url=url, status=404, headers={}, body=None,
                error="HTTP 404", fetched_at=fetched_at,
            )
        status, content_type, body = entry
        return FetchResult(
            url=url,
            final_url=url,
            status=status,
            headers={"Content-Type": content_type},
            body=body if status == 200 else None,
            error=None if status == 200 else f"HTTP {status}",
            fetched_at=fetched_at,
        )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fetcher() -> FakeFetcher:
    return FakeFetcher()


@pytest.fixture
def ports(clock, fetcher) -> EnginePorts:
    return EnginePorts(
        fetcher=fetcher,
        robots=RobotsService(fetcher, MemoryRobotsCache(), clock),
        visited=MemoryVisitedStore(),
        gate=MemoryHostGate(clock),
        frontier=MemoryFrontier(),
        pages=MemoryPageSink(),
        records=MemoryRecordSink(),
        clock=clock,
    )


PRICE_FIELD = FieldSpec(field_id="fld_price", name="price", type="number")
TITLE_FIELD = FieldSpec(field_id="fld_title", name="title", type="string")


def make_intent(
    *,
    seeds: tuple[str, ...] = ("https://shop.example/",),
    engine: str = "css",
    mappings: dict | None = None,
    fields: tuple[FieldSpec, ...] = (TITLE_FIELD, PRICE_FIELD),
    scope: Scope | None = None,
    politeness: Politeness | None = None,
    store_raw_pages: bool = True,
    extra_templates: tuple[TemplateSpec, ...] = (),
    primary_scope: TemplateScope | None = None,
    system_templates: tuple[TemplateSpec, ...] = (),
) -> ExecutionIntent:
    return ExecutionIntent(
        execution_id="exec_test",
        org_id="org_test",
        job_id="job_test",
        seeds=seeds,
        dataset_id="ds_test",
        templates=(
            TemplateSpec(
                template_id="tmpl_test",
                engine=engine,  # type: ignore[arg-type]
                mappings=TemplateSpec.normalize_mappings(
                    mappings if mappings is not None else {"fld_title": "h1", "fld_price": ".price"}
                ),
                scope=primary_scope,
            ),
        ) + extra_templates,
        system_templates=system_templates,
        schema=SchemaSpec(schema_id="schema_test", fields=fields),
        scope=scope or Scope(max_pages=50),
        politeness=politeness or Politeness(requests_per_second=1000.0),
        store_raw_pages=store_raw_pages,
    )
