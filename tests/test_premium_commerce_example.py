"""Controlled, network-free contracts for the ten-store local thesis example."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit, urlunsplit

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
sys.path.insert(0, str(EXAMPLES))

from marketplace.premium_commerce.audit import audit_robots, conservative_robots_check
from marketplace.premium_commerce.controlled import ControlledFetcher, product_html
from marketplace.premium_commerce.local import portable_summary, provision, run_demo
from marketplace.premium_commerce.recipes import CUSTOM_FIELDS, FICTIONAL_SOURCES, SOURCES, build_recipes, field_ids, source_for_url
from pulsecrawl import Workspace, validate_template_stack
from pulsecrawl.core.model import FetchResult
from pulsecrawl.core.urls import template_scope_matches


def validate(source, html, *, expected=None, required=("name", "currency")):
    ids = field_ids()
    recipe = next(item for item in build_recipes(sources=FICTIONAL_SOURCES) if item["slug"] == source.slug)
    parts = urlsplit(source.sample_url)
    return validate_template_stack(
        recipe["templateStack"],
        [{"url": source.sample_url, "body": html,
          "expectedRecords": [{ids[key]: value for key, value in expected.items()}] if expected else []},
         {"url": urlunsplit(parts._replace(path="/collections/all", query="")),
          "body": html, "role": "negative"},
         {"url": "https://foreign.example" + parts.path, "body": html, "role": "negative"}],
        required_field_ids=[ids[key] for key in required],
        field_types={ids[name]: kind for name, kind, _ in CUSTOM_FIELDS},
    )


def test_exact_user_selected_ten_sources_and_no_excluded_stores():
    assert {source.slug for source in SOURCES} == {
        "lululemon", "alo", "nordstrom", "revolve", "nike", "adidas", "new-balance", "on", "hoka", "ugg"
    }
    assert len(build_recipes()) == 10
    assert all(item["liveStatus"] == "disabled-provisional" for item in build_recipes())
    assert len({item["template_id"] for recipe in build_recipes() for item in recipe["templateStack"]}) == 30


@pytest.mark.parametrize("source", SOURCES, ids=lambda source: source.slug)
def test_all_product_scopes_and_wrong_host_collection_negatives(source):
    assert source_for_url(source.sample_url) == source
    assert template_scope_matches(source.sample_url, hosts=(source.host,), url_patterns=source.paths)
    parts = urlsplit(source.sample_url)
    for negative in ("https://foreign.example" + parts.path,
                     "https://" + source.host + "/collections/all",
                     "https://" + source.host + "/", "https://" + source.host + "/search?q=shoes"):
        assert not template_scope_matches(negative, hosts=(source.host,), url_patterns=source.paths)
        with pytest.raises(ValueError):
            source_for_url(negative)


@pytest.mark.parametrize("source", FICTIONAL_SOURCES, ids=lambda source: source.slug)
@pytest.mark.parametrize("layout", ["jsonld", "graph", "meta", "css", "malformed"])
def test_scoped_extraction_and_fallback_with_original_controlled_inputs(source, layout):
    report = validate(source, product_html(source, 0, layout=layout),
                      expected={"current_price": 120.0, "currency": "USD", "store": source.store})
    assert report["passed"], report
    assert report["summary"]["negativeMatches"] == 0
    assert not report["oracleMismatches"]


@pytest.mark.parametrize("source", FICTIONAL_SOURCES, ids=lambda source: source.slug)
def test_range_is_not_misreported_as_selected_or_regular_price(source):
    report = validate(source, product_html(source, 0, layout="range"),
                      expected={"low_price": 80.0, "high_price": 150.0, "currency": "USD"})
    assert report["passed"], report
    row = report["pages"][0]["coercedRecords"][0]
    assert field_ids()["current_price"] not in row
    assert field_ids()["regular_price"] not in row


def test_variant_context_identifier_and_missing_currency_are_not_invented():
    source = FICTIONAL_SOURCES[0]
    report = validate(source, product_html(source, 0), expected={
        "color": "SYNTHETIC Black", "size": "SYNTHETIC M",
        "sku": "SYNTHETIC-shop-01-M-BLACK", "brand": "SYNTHETIC brand",
        "offer_url": source.sample_url,
    })
    assert report["passed"]
    html = product_html(source, 0, layout="meta").replace('property="product:price:currency"', 'property="unmapped"')
    report = validate(source, html, required=("name",))
    assert report["passed"]
    assert field_ids()["currency"] not in report["pages"][0]["records"][0]
    assert "color=black" in source.sample_url


def test_numeric_coercion_and_first_offer_semantics_are_explicit():
    source = FICTIONAL_SOURCES[0]
    html = '<script type="application/ld+json">' + json.dumps({
        "@type": "Product", "name": "SYNTHETIC", "offers": [
            {"price": "1,299.50", "priceCurrency": "USD", "sku": "FIRST-M"},
            {"price": "79.00", "priceCurrency": "USD", "sku": "SECOND-L"},
        ]}) + '</script>'
    report = validate(source, html, expected={"current_price": 1299.5, "offer_sku": "FIRST-M"})
    assert report["passed"]
    assert len(report["pages"][0]["records"]) == 1


def test_in_scope_empty_page_is_not_a_literal_only_product_record():
    source = FICTIONAL_SOURCES[0]
    report = validate(source, "<h1>Access denied</h1>", required=("name",))
    assert report["passed"] is False
    assert report["pages"][0]["records"] == []


def test_provisioning_is_local_bounded_and_imports_do_not_use_network(tmp_path):
    with Workspace.init(tmp_path / "configured") as workspace:
        value = provision(workspace)
        job = value["job"]
        assert value["dataset"]["mode"] == "append_all"
        assert job["scope"]["maxDepth"] == 0
        assert job["scope"]["maxUrlsPerExecution"] == 10
        assert job["scope"]["maxUrlsTotal"] == 20
        assert len(job["seeds"]) == 10
        assert job["politeness"]["respectRobotsTxt"] is True
        assert not workspace.schedules.list()
        assert workspace.validate()["valid"]


def test_two_actual_local_executions_publish_history_and_pinned_versions(tmp_path, monkeypatch):
    import aiohttp

    def no_network(*args, **kwargs):
        raise AssertionError("offline demonstration attempted network access")

    monkeypatch.setattr(aiohttp, "ClientSession", no_network)
    root = tmp_path / "history"
    report = run_demo(root)
    expected = json.loads((EXAMPLES / "marketplace/premium_commerce/controlled-demo-summary.json").read_text())
    assert portable_summary(report) == expected
    with Workspace(root) as workspace:
        assert workspace.datasets.query(report["datasetId"],
            "SELECT count(distinct _execution_id), count(distinct _source_url), count(*) FROM dataset"
        )["rows"] == [[2, 10, 20]]
    with pytest.raises(ValueError, match="fresh workspace"):
        run_demo(root)


def test_controlled_fetcher_unknown_urls_and_hard_cap():
    fetcher = ControlledFetcher(0)
    result = asyncio.run(fetcher.fetch("https://foreign.example/", user_agent="test"))
    assert result.status == 404
    fetcher.calls = ["x"] * 20
    with pytest.raises(RuntimeError, match="cap exceeded"):
        asyncio.run(fetcher.fetch(SOURCES[0].sample_url, user_agent="test"))


def test_live_execution_is_rejected_before_workspace_or_network(monkeypatch, tmp_path):
    from marketplace.premium_commerce.local import main
    target = tmp_path / "must-not-be-created"
    monkeypatch.setattr(sys, "argv", ["local.py", "--live", "--workspace", str(target)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not target.exists()


def test_conservative_audit_handles_wildcards_and_does_not_treat_403_as_permission():
    ua = "PulseCrawlResearch/0.1 (+https://github.com/pulsecrawl/PulseCrawl)"
    assert not conservative_robots_check("User-agent: *\nDisallow: /*dwvar\n", SOURCES[-1].sample_url, ua)
    assert conservative_robots_check("User-agent: *\nDisallow: /cart\n", SOURCES[0].sample_url, ua)
    class RobotsOnly:
        async def fetch(self, url, *, user_agent):
            assert url.endswith("/robots.txt")
            return FetchResult(url=url, final_url=url, status=403, headers={"content-type": "text/html"},
                               body="Denied", error=None, fetched_at=None)
    report = asyncio.run(audit_robots(SOURCES, ua, fetcher=RobotsOnly()))
    assert len(report["checks"]) == 10
    assert all(not row["conservativelyEligible"] and row["productRequests"] == 0 for row in report["checks"])
    with pytest.raises(ValueError, match="contact"):
        asyncio.run(audit_robots(SOURCES, "Googlebot", fetcher=RobotsOnly()))


def test_truncated_robots_is_not_interpreted_as_permission():
    class TruncatedRobots:
        async def fetch(self, url, *, user_agent):
            return FetchResult(url=url, final_url=url, status=200,
                               headers={"content-type": "text/plain"}, body="User-agent: *\nAllow: /\n",
                               body_truncated=True, error=None, fetched_at=None)
    report = asyncio.run(audit_robots((SOURCES[0],),
        "PulseCrawlResearch/0.1 (+https://github.com/pulsecrawl/PulseCrawl)", fetcher=TruncatedRobots()))
    assert report["checks"][0]["conservativelyEligible"] is False
