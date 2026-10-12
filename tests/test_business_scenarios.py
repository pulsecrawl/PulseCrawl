"""Deterministic end-to-end business scenarios for the local OSS product.

These tests intentionally assert records, URL history, execution accounting,
and query results together.  A scenario is only considered correct when the
user-visible data and all durable bookkeeping agree.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pyarrow.parquet as pq
import pytest
from pulsecrawl.core.model import FetchResult

from pulsecrawl import Workspace


ARTICLE_FIELDS = [
    {"fieldId": "fld_title", "name": "title", "type": "string"},
    {"fieldId": "fld_url", "name": "canonical", "type": "url"},
]


class FixtureFetcher:
    def __init__(self, pages: dict[str, str], *, minute: int = 0):
        self.pages = pages
        self.calls: list[str] = []
        self.fetched_at = datetime(2026, 9, 1, 12, minute, tzinfo=timezone.utc)

    async def fetch(self, url, *, user_agent):
        self.calls.append(url)
        body = self.pages.get(url)
        return FetchResult(
            url=url,
            final_url=url,
            status=200 if body is not None else 404,
            headers={"content-type": "text/html; charset=utf-8"},
            body=body,
            error=None if body is not None else "HTTP 404",
            fetched_at=self.fetched_at,
        )


@pytest.fixture
def workspace(tmp_path):
    value = Workspace.init(tmp_path / "workspace", name="business-scenarios")
    yield value
    value.close()


def create_job(
    workspace,
    *,
    name: str,
    fields=ARTICLE_FIELDS,
    mode: str = "append_all",
    identity_field: str = "_source_url",
    seeds=("https://case.example/",),
    templates=None,
    max_urls: int = 50,
):
    dataset = workspace.datasets.create(
        f"{name} data",
        fields=fields,
        mode=mode,
        identity_field=identity_field,
    )
    job = workspace.jobs.create(
        name,
        seeds=seeds,
        dataset_id=dataset["datasetId"],
        templates=templates
        or [{
            "engine": "css",
            "mappings": {
                "fld_title": "h1",
                "fld_url": "link[rel=canonical]@href",
            },
        }],
        scope={
            "maxDepth": 2,
            "maxUrlsPerExecution": max_urls,
            "maxUrlsTotal": max_urls * 10,
        },
        politeness={"respectRobotsTxt": False, "requestsPerSecond": 1000},
    )
    return dataset, job


def rows(workspace, dataset, sql):
    return workspace.datasets.query(dataset["datasetId"], sql, row_cap=10_000)["rows"]


@pytest.mark.parametrize(
    ("mode", "expected_rows"),
    [("append_all", 2), ("new_urls_only", 1)],
)
def test_source_identity_mode_matrix_tracks_repeat_history(
    workspace, mode, expected_rows
):
    dataset, job = create_job(workspace, name=mode, mode=mode)
    page = (
        '<h1>Same entity</h1>'
        '<link rel="canonical" href="https://case.example/canonical">'
    )
    first = workspace.jobs.run(
        job["jobId"], fetcher=FixtureFetcher({"https://case.example/": page})
    )
    second = workspace.jobs.run(
        job["jobId"],
        fetcher=FixtureFetcher({"https://case.example/": page}, minute=1),
    )

    assert first["stats"]["materializedRows"] == 1
    assert second["stats"]["materializedRows"] == expected_rows - 1
    assert rows(workspace, dataset, "SELECT count(*) FROM dataset") == [[expected_rows]]
    [identity] = workspace.datasets.urls(dataset["datasetId"])["urls"]
    assert identity["urlIdentity"] == "https://case.example/"
    assert identity["seenCount"] == identity["executionCount"] == 2
    assert identity["firstExecutionId"] == first["executionId"]
    assert identity["lastExecutionId"] == second["executionId"]


@pytest.mark.parametrize(
    ("mode", "expected_rows"),
    [("append_all", 2), ("new_urls_only", 1)],
)
def test_custom_identity_normalizes_case_ports_fragments_and_query_order(
    workspace, mode, expected_rows
):
    dataset, job = create_job(
        workspace,
        name=f"custom-{mode}",
        mode=mode,
        identity_field="fld_url",
    )
    first_page = (
        '<h1>First</h1><link rel="canonical" '
        'href="HTTPS://Case.Example:443/item/%7e?a=1&amp;b=2#first">'
    )
    second_page = (
        '<h1>Updated</h1><link rel="canonical" '
        'href="https://case.example/item/~?b=2&amp;a=1#second">'
    )
    workspace.jobs.run(
        job["jobId"], fetcher=FixtureFetcher({"https://case.example/": first_page})
    )
    workspace.jobs.run(
        job["jobId"],
        fetcher=FixtureFetcher({"https://case.example/": second_page}, minute=1),
    )

    assert rows(
        workspace,
        dataset,
        "SELECT title, canonical FROM dataset ORDER BY _crawled_at",
    ) == (
        [["First", "https://case.example/item/%7e?a=1&b=2"]]
        if expected_rows == 1
        else [
            ["First", "https://case.example/item/%7e?a=1&b=2"],
            ["Updated", "https://case.example/item/~?b=2&a=1"],
        ]
    )
    [identity] = workspace.datasets.urls(dataset["datasetId"])["urls"]
    assert identity["urlIdentity"] == "https://case.example/item/~?a=1&b=2"
    assert identity["seenCount"] == identity["executionCount"] == 2


def test_new_urls_only_keeps_rows_without_a_valid_custom_identity_visible(workspace):
    dataset, job = create_job(
        workspace,
        name="missing-identities",
        mode="new_urls_only",
        identity_field="fld_url",
    )
    pages = ["<h1>No canonical</h1>", '<h1>Bad canonical</h1><link href="mailto:x@y.z">']
    for minute, page in enumerate(pages):
        result = workspace.jobs.run(
            job["jobId"],
            fetcher=FixtureFetcher({"https://case.example/": page}, minute=minute),
        )
        assert result["stats"]["materializedRows"] == 1

    assert rows(
        workspace,
        dataset,
        "SELECT title, canonical, _url_identity FROM dataset ORDER BY _crawled_at",
    ) == [["No canonical", None, None], ["Bad canonical", None, None]]
    assert workspace.datasets.urls(dataset["datasetId"])["urls"] == []


def test_jsonld_multiple_entities_are_complete_and_suppressed_only_on_later_runs(
    workspace,
):
    fields = [
        {"fieldId": "fld_name", "name": "name", "type": "string"},
        {"fieldId": "fld_price", "name": "price", "type": "number"},
        {"fieldId": "fld_url", "name": "canonical", "type": "url"},
    ]
    dataset, job = create_job(
        workspace,
        name="catalog",
        fields=fields,
        mode="new_urls_only",
        identity_field="fld_url",
        templates=[{
            "engine": "jsonld",
            "mappings": {
                "fld_name": "Product.name",
                "fld_price": "Product.offers.price",
                "fld_url": "Product.url",
            },
        }],
    )
    page = """<script type="application/ld+json">[
      {"@type":"Product","name":"Blue Shirt","url":"/p/blue","offers":{"price":"19.95"}},
      {"@type":"Product","name":"Red Shirt","url":"/p/red","offers":{"price":"24.50"}}
    ]</script>"""
    first = workspace.jobs.run(
        job["jobId"], fetcher=FixtureFetcher({"https://case.example/": page})
    )
    second = workspace.jobs.run(
        job["jobId"],
        fetcher=FixtureFetcher({"https://case.example/": page}, minute=1),
    )

    assert first["stats"]["materializedRows"] == 2
    assert second["stats"]["materializedRows"] == 0
    assert rows(
        workspace, dataset, "SELECT name, price, canonical FROM dataset ORDER BY name"
    ) == [
        ["Blue Shirt", 19.95, "https://case.example/p/blue"],
        ["Red Shirt", 24.5, "https://case.example/p/red"],
    ]
    history = workspace.datasets.urls(dataset["datasetId"])["urls"]
    assert len(history) == 2
    assert {(item["seenCount"], item["executionCount"]) for item in history} == {(2, 2)}


def test_ecommerce_catalog_business_scenario(workspace):
    fields = [
        {"fieldId": "fld_name", "name": "name", "type": "string"},
        {"fieldId": "fld_price", "name": "price", "type": "number"},
        {"fieldId": "fld_available", "name": "available", "type": "boolean"},
        {"fieldId": "fld_url", "name": "canonical", "type": "url"},
    ]
    dataset, job = create_job(
        workspace,
        name="commerce",
        fields=fields,
        identity_field="fld_url",
        templates=[{
            "engine": "css",
            "mappings": {
                "fld_name": "h1",
                "fld_price": ".price",
                "fld_available": ".available",
                "fld_url": "link[rel=canonical]@href",
            },
        }],
        seeds=("https://case.example/p/sku-1",),
    )
    page = (
        '<h1>Trail shoes</h1><span class="price">$1,299.00</span>'
        '<span class="available">yes</span>'
        '<link rel="canonical" href="/p/sku-1">'
    )
    result = workspace.jobs.run(
        job["jobId"],
        fetcher=FixtureFetcher({"https://case.example/p/sku-1": page}),
    )
    assert result["status"] == "succeeded"
    assert rows(workspace, dataset, "SELECT name,price,available,canonical FROM dataset") == [
        ["Trail shoes", 1299.0, True, "https://case.example/p/sku-1"]
    ]


def test_news_incremental_monitor_business_scenario(workspace):
    dataset, job = create_job(
        workspace,
        name="news",
        mode="new_urls_only",
        identity_field="fld_url",
    )
    first_page = (
        '<h1>Home</h1><link rel="canonical" href="/">'
        '<a href="/story/1">one</a><a href="/story/2">two</a>'
    )
    stories = {
        "https://case.example/": first_page,
        "https://case.example/story/1": '<h1>One</h1><link rel="canonical" href="/story/1">',
        "https://case.example/story/2": '<h1>Two</h1><link rel="canonical" href="/story/2">',
    }
    first = workspace.jobs.run(job["jobId"], fetcher=FixtureFetcher(stories))
    stories["https://case.example/"] = first_page + '<a href="/story/3">three</a>'
    stories["https://case.example/story/3"] = (
        '<h1>Three</h1><link rel="canonical" href="/story/3">'
    )
    second = workspace.jobs.run(job["jobId"], fetcher=FixtureFetcher(stories, minute=1))

    assert first["stats"]["materializedRows"] == 3
    assert second["stats"]["materializedRows"] == 1
    assert rows(workspace, dataset, "SELECT title FROM dataset ORDER BY title") == [
        ["Home"], ["One"], ["Three"], ["Two"]
    ]
    assert len(workspace.datasets.urls(dataset["datasetId"], newness="repeat")["urls"]) == 3
    assert len(workspace.datasets.urls(dataset["datasetId"], newness="new")["urls"]) == 1


def test_job_listing_schema_fidelity_and_nulls(workspace):
    fields = [
        {"fieldId": "fld_title", "name": "title", "type": "string"},
        {"fieldId": "fld_salary", "name": "salary", "type": "number"},
        {"fieldId": "fld_remote", "name": "remote", "type": "boolean"},
        {"fieldId": "fld_posted", "name": "posted_at", "type": "datetime"},
        {"fieldId": "fld_url", "name": "apply_url", "type": "url"},
        {"fieldId": "fld_optional", "name": "department", "type": "string"},
    ]
    mappings = {
        "fld_title": "h1",
        "fld_salary": ".salary",
        "fld_remote": ".remote",
        "fld_posted": "time@datetime",
        "fld_url": "a.apply@href",
        "fld_optional": ".department",
    }
    dataset, job = create_job(
        workspace,
        name="jobs",
        fields=fields,
        identity_field="fld_url",
        templates=[{"engine": "css", "mappings": mappings}],
        seeds=("https://case.example/jobs/42",),
    )
    page = (
        '<h1>Data Engineer</h1><span class="salary">€80.000,50</span>'
        '<span class="remote">true</span>'
        '<time datetime="2026-09-01T08:30:00-04:00"></time>'
        '<a class="apply" href="../apply/42">Apply</a>'
    )
    workspace.jobs.run(
        job["jobId"],
        fetcher=FixtureFetcher({"https://case.example/jobs/42": page}),
    )

    assert rows(
        workspace,
        dataset,
        "SELECT title,salary,remote,posted_at,apply_url,department FROM dataset",
    ) == [[
        "Data Engineer",
        80000.5,
        True,
        "2026-09-01T12:30:00+00:00",
        "https://case.example/apply/42",
        None,
    ]]
    file_path = workspace.path / "datasets" / dataset["datasetId"] / workspace.datasets.files(
        dataset["datasetId"]
    )[0]["path"]
    schema = pq.read_schema(file_path)
    assert str(schema.field("salary").type) == "double"
    assert str(schema.field("remote").type) == "bool"
    assert str(schema.field("posted_at").type) == "timestamp[us, tz=UTC]"


def test_marketplace_duplicate_canonicals_keep_rows_and_one_entity(workspace):
    dataset, job = create_job(
        workspace,
        name="marketplace",
        identity_field="fld_url",
        seeds=(
            "https://case.example/listing/7?utm_source=a",
            "https://case.example/listing/7?utm_source=b",
        ),
    )
    pages = {
        seed: (
            f"<h1>{seed[-1]}</h1>"
            '<link rel="canonical" href="https://case.example/listing/7">'
        )
        for seed in job["seeds"]
    }
    result = workspace.jobs.run(job["jobId"], fetcher=FixtureFetcher(pages))

    assert result["stats"]["materializedRows"] == 2
    assert rows(workspace, dataset, "SELECT count(*),count(distinct canonical) FROM dataset") == [
        [2, 1]
    ]
    [identity] = workspace.datasets.urls(dataset["datasetId"])["urls"]
    assert identity["seenCount"] == 2
    assert identity["executionCount"] == 1


def test_append_all_change_monitor_retains_every_observation(workspace):
    dataset, job = create_job(
        workspace,
        name="changes",
        mode="append_all",
        identity_field="fld_url",
    )
    for minute, value in enumerate(("In stock", "Out of stock", "In stock")):
        page = f'<h1>{value}</h1><link rel="canonical" href="/item/1">'
        workspace.jobs.run(
            job["jobId"],
            fetcher=FixtureFetcher({"https://case.example/": page}, minute=minute),
        )
    assert rows(
        workspace,
        dataset,
        "SELECT title FROM dataset ORDER BY _crawled_at",
    ) == [["In stock"], ["Out of stock"], ["In stock"]]
    [identity] = workspace.datasets.urls(dataset["datasetId"])["urls"]
    assert (identity["seenCount"], identity["executionCount"]) == (3, 3)


def test_multi_site_templates_do_not_cross_contaminate_business_rules(workspace):
    fields = [
        {"fieldId": "fld_title", "name": "title", "type": "string"},
        {"fieldId": "fld_source", "name": "source", "type": "string"},
    ]
    templates = [
        {
            "template_id": "site-a",
            "engine": "css",
            "hosts": ["a.example"],
            "mappings": {"fld_title": "h1", "fld_source": "literal:Site A"},
        },
        {
            "template_id": "site-b",
            "engine": "css",
            "hosts": ["b.example"],
            "mappings": {"fld_title": "h2", "fld_source": "literal:Site B"},
        },
    ]
    dataset, job = create_job(
        workspace,
        name="multi-site",
        fields=fields,
        seeds=("https://a.example/", "https://b.example/"),
        templates=templates,
    )
    workspace.jobs.run(
        job["jobId"],
        fetcher=FixtureFetcher({
            "https://a.example/": "<h1>Alpha</h1><h2>wrong A</h2>",
            "https://b.example/": "<h1>wrong B</h1><h2>Beta</h2>",
        }),
    )
    assert rows(workspace, dataset, "SELECT title,source FROM dataset ORDER BY source") == [
        ["Alpha", "Site A"], ["Beta", "Site B"]
    ]
