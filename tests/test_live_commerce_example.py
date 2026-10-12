"""Network-free contract tests, NOT real-website case-study evidence."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
sys.path.insert(0, str(EXAMPLES))

from marketplace.premium_commerce import live
from marketplace.premium_commerce.controlled import product_html
from marketplace.premium_commerce.recipes import FICTIONAL_SOURCES, SOURCES
from pulsecrawl import Workspace
from pulsecrawl.core.model import FetchResult


def reviewed(tmp_path):
    value = json.loads(live.DEFAULT_MANIFEST.read_text())
    value["sources"][0].update(enabled=True, accessReview={
        "status": "reviewed", "basis": "Contract test only; no real HTTP is authorized",
        "reviewedAt": "2026-01-01T00:00:00+00:00"})
    path = tmp_path / "reviewed.json"
    path.write_text(json.dumps(value))
    return live.load_manifest(path, require_enabled=True), path


def test_published_plan_is_disabled_and_synthetic_sources_are_fictional():
    data = live.load_manifest(live.DEFAULT_MANIFEST)
    assert data["status"] == "not-run" and data["recordHtml"] is False
    assert data["evidence"]["executions"] == []
    assert all(not s["enabled"] for s in data["sources"])
    assert all(s.host.endswith(".example") for s in FICTIONAL_SOURCES)
    with pytest.raises(ValueError, match="fictional"):
        product_html(SOURCES[0], 0)
    with pytest.raises(ValueError, match="no reviewed sources"):
        live.load_manifest(live.DEFAULT_MANIFEST, require_enabled=True)


@pytest.mark.parametrize("change", ["review", "rate", "integer", "url", "body"])
def test_invalid_live_configuration_is_rejected_before_network(tmp_path, change):
    data, path = reviewed(tmp_path)
    if change == "review":
        data["sources"][0]["accessReview"]["basis"] = ""
    elif change == "rate":
        data["limits"]["requestsPerSecond"] = 1000
    elif change == "integer":
        data["limits"]["maxExecutions"] = 1.5
    elif change == "url":
        data["sources"][0]["url"] = "http://127.0.0.1/"
    else:
        data["recordHtml"] = True
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        live.load_manifest(path, require_enabled=True)


def test_plan_and_init_do_not_contact_sites_or_create_schedules(tmp_path, monkeypatch, capsys):
    def no_network(*args, **kwargs):
        raise AssertionError("unexpected HTTP client")
    monkeypatch.setattr(live, "AiohttpFetcher", no_network)
    monkeypatch.setattr(sys, "argv", ["live", "plan"])
    live.main()
    assert json.loads(capsys.readouterr().out)["networkRequests"] == 0
    manifest, _ = reviewed(tmp_path)
    root = tmp_path / "workspace"
    assert live.initialize(manifest, root)["status"] == "configured-not-run"
    with Workspace(root) as workspace:
        job = workspace.jobs.list()[0]
        assert job["storeRawPages"] is False
        assert job["scope"]["maxDepth"] == 0
        assert job["politeness"]["respectRobotsTxt"] is True
        assert not workspace.schedules.list()
    with pytest.raises(ValueError, match="--network"):
        live.execute(manifest, root, network=False)
    with pytest.raises(ValueError, match="fresh workspace"):
        live.initialize(manifest, root)


def test_observed_execution_retains_real_runtime_outputs_without_html_or_fallback(tmp_path, monkeypatch):
    """Injected transport exercises the runner; outputs stay in pytest's tempdir."""
    calls = []
    deny_robots = False
    class ContractHTTP:
        def __init__(self, **kwargs):
            assert kwargs["retries"] == 1 and not kwargs["allow_redirects"]
            assert not kwargs["allow_private_networks"]
        async def fetch(self, url, *, user_agent):
            calls.append(url)
            robots = url.endswith("/robots.txt")
            body = ("User-agent: *\nDisallow: /\n" if deny_robots else "User-agent: *\nAllow: /\n") if robots else (
                '<script type="application/ld+json">{"@type":"Product","name":"Contract test product",'
                '"offers":{"price":"42.50","priceCurrency":"EUR"}}</script>')
            return FetchResult(url=url, final_url=url, status=200,
                headers={"content-type": "text/plain" if robots else "text/html"},
                body=body, error=None, fetched_at=datetime.now(timezone.utc), body_bytes=len(body))
        async def close(self):
            pass
    async def no_wait(*args):
        pass
    monkeypatch.setattr(live, "AiohttpFetcher", ContractHTTP)
    monkeypatch.setattr(live.asyncio, "sleep", no_wait)
    manifest, _ = reviewed(tmp_path)
    root = tmp_path / "workspace"
    live.initialize(manifest, root)
    result = live.execute(manifest, root, network=True)
    assert result["status"] == "succeeded"
    assert result["observationChecks"] == {"rows": 1, "namedProducts": 1, "pricedProductsWithCurrency": 1}
    assert result["committedVersion"]["version"] == 1
    assert len(calls) == 2
    assert all("body" not in row and "headers" not in row for row in result["physicalRequests"])
    assert not list(root.rglob("*.html"))
    state = json.loads((root / live.STATE_FILE).read_text())
    assert "application/ld+json" not in json.dumps(state)
    with pytest.raises(ValueError, match="minimum repeat interval"):
        live.execute(manifest, root, network=True)
    # Advance only the contract-test reservation. A live user must actually wait.
    state["runs"][0]["startedAt"] = "2026-01-01T00:00:00+00:00"
    live.save(root / live.STATE_FILE, state)
    deny_robots = True
    second = live.execute(manifest, root, network=True)
    assert len(calls) == 3  # Fresh robots check despite the runtime's cached allow.
    assert second["observationChecks"]["rows"] == 0
    assert second["refusals"][0]["reason"] == "robots-preflight-denied-or-unreadable"
    assert len(second["observations"]["rows"]) == 1  # Only the first run, no invented second row.
    with pytest.raises(ValueError, match="cap reached"):
        live.execute(manifest, root, network=True)


def test_changed_configuration_lock_and_notes_are_explicit(tmp_path):
    manifest, _ = reviewed(tmp_path)
    root = tmp_path / "workspace"
    live.initialize(manifest, root)
    modified = json.loads(json.dumps(manifest))
    modified["recipes"][0]["templateStack"][0]["mappings"] = {}
    with pytest.raises(ValueError, match="configuration changed"):
        live.execute(modified, root, network=True)
    lock = root / "case-study.lock"
    lock.touch()
    with pytest.raises(ValueError, match="locked"):
        live.execute(manifest, root, network=True)
    assert lock.exists()
    lock.unlink()
    note = live.add_note(root, "setup", "Contract test note; not participant evidence.")
    assert note["stage"] == "setup"


def test_observed_fetcher_rejects_scope_expansion_and_bad_user_agent(tmp_path):
    manifest, _ = reviewed(tmp_path)
    fetcher = live.ObservedFetcher(manifest)
    assert asyncio.run(fetcher.fetch("https://foreign.example/", user_agent=manifest["userAgent"])).status == 403
    assert asyncio.run(fetcher.fetch(SOURCES[0].sample_url, user_agent="Googlebot")).status == 403
    assert fetcher.events == []
