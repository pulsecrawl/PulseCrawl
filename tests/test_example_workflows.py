"""Offline contracts for example imports, commands and public API workflows."""

from dataclasses import replace
import importlib
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from examples import hosted_quickstart, local_quickstart, workspace_quickstart
from examples.shared.catalog import CASES
from examples.shared.fixtures import EXAMPLE_URL, FixtureFetcher
from examples.shared.hosted import HostedCaseProvisioner
from examples.shared.local import LocalCaseProvisioner
from examples.shared.validation import GovernedSampleReader, RecipeValidator
from pulsecrawl import Workspace
from pulsecrawl.domain.crawling.model import FetchResult


def _environment():
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join([str(PACKAGE / "src"), str(PACKAGE)])
    for name in ("PULSECRAWL_API_KEY", "PULSECRAWL_BASE_URL", "PULSECRAWL_USER_AGENT"):
        environment.pop(name, None)
    return environment


def test_every_example_import_is_network_and_resource_creation_free(tmp_path):
    code = """
import importlib, pkgutil, socket
from pulsecrawl import Workspace, PulseCrawl
from pulsecrawl.adapters.outbound.http.fetcher import AiohttpFetcher
def forbidden(*args, **kwargs):
    raise AssertionError("examples must not create resources or connect on import")
socket.socket.connect = forbidden
socket.create_connection = forbidden
Workspace.init = forbidden
PulseCrawl.__init__ = forbidden
AiohttpFetcher.__init__ = forbidden
import examples
modules = list(pkgutil.walk_packages(examples.__path__, "examples."))
assert len(modules) > 40
for module in modules:
    importlib.import_module(module.name)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=_environment(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


DIRECT_COMMANDS = [
    "local_quickstart.py",
    "workspace_quickstart.py",
    "hosted_quickstart.py",
    "local_cases.py",
    "hosted_cases.py",
    "chihuahua_news.py",
    *[f"{key}/{mode}.py" for key in CASES for mode in ("local", "hosted")],
    "jobsearch/validate_recipes.py",
    "marketplace/clothes/validate_recipes.py",
    "marketplace/other_industries/validate_recipes.py",
]


@pytest.mark.parametrize("entry", DIRECT_COMMANDS)
def test_direct_entry_points_help_works_from_another_directory(entry, tmp_path):
    result = subprocess.run(
        [sys.executable, str(PACKAGE / "examples" / entry), "--help"],
        cwd=tmp_path,
        env=_environment(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "module",
    [
        "examples.news.chihuahua.hosted",
        "examples.news.stocks.local",
        "examples.marketplace.premium_commerce.local",
        "examples.marketplace.premium_commerce.live",
        "examples.marketplace.premium_commerce.audit",
    ],
)
def test_module_entry_points_help_is_safe(module, tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        cwd=tmp_path,
        env=_environment(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_memory_quickstart_uses_fictional_transport():
    result = local_quickstart.run()
    assert result.records[0]["title"] == "Hello PulseCrawl"
    assert result.records[0]["_source_url"] == EXAMPLE_URL
    assert result.stats["pagesFetched"] == 1


def test_workspace_quickstart_publishes_and_refuses_to_overwrite(tmp_path):
    path = tmp_path / "quickstart"
    result = workspace_quickstart.run(path)
    assert result["execution"]["status"] == "succeeded"
    assert result["query"]["rows"] == [["Hello PulseCrawl", "Offline example"]]
    assert result["validation"]["valid"]
    with pytest.raises(ValueError, match="fresh or empty"):
        workspace_quickstart.run(path)
    with Workspace(path) as reopened:
        assert reopened.datasets.query(
            result["datasetId"], "SELECT count(*) FROM dataset"
        )["rows"] == [[1]]


def test_quickstarts_require_explicit_live_arguments(monkeypatch, capsys):
    monkeypatch.delenv("PULSECRAWL_USER_AGENT", raising=False)
    with pytest.raises(SystemExit) as error:
        local_quickstart.main(["--live"])
    assert error.value.code == 2
    with pytest.raises(SystemExit) as error:
        hosted_quickstart.main(["--run"])
    assert error.value.code == 2
    monkeypatch.setattr(
        hosted_quickstart,
        "PulseCrawl",
        Mock(side_effect=AssertionError("must not connect")),
    )
    hosted_quickstart.main([])
    assert "Plan only" in capsys.readouterr().out


def test_hosted_quickstart_discovers_schema_and_does_not_run_implicitly():
    client = Mock()
    client.templates.list.return_value = [
        {"templateId": "tmpl_sys_meta_page", "outputSchemaId": "schema_current"}
    ]
    client.datasets.create.return_value = {"datasetId": "dataset"}
    client.jobs.create.return_value = {"jobId": "job"}
    result = hosted_quickstart.provision(
        client,
        url="https://example.com/",
        user_agent="ReviewedCrawler (+https://operator.example/contact)",
    )
    client.datasets.create.assert_called_once_with(
        "quickstart pages", schema_id="schema_current"
    )
    client.jobs.run.assert_not_called()
    assert result["execution"] is None


def test_local_provisioning_is_repeatable_and_does_not_crawl(tmp_path, monkeypatch):
    with Workspace.init(tmp_path / "cases") as workspace:
        provisioner = LocalCaseProvisioner(workspace)
        monkeypatch.setattr(
            workspace.jobs, "run", Mock(side_effect=AssertionError("must not crawl"))
        )
        first = provisioner.provision(CASES["news/stocks"])
        second = provisioner.provision(CASES["news/stocks"])
        assert first == second
        assert len(workspace.jobs.list()) == 1
        assert len(workspace.datasets.list()) == 1
        with pytest.raises(RuntimeError, match="differs from the recipe"):
            provisioner.provision(
                replace(CASES["news/stocks"], dataset_mode="append_all")
            )
        assert len(workspace.jobs.list()) == 1


def test_hosted_provisioning_rejects_incompatible_job_without_archiving(monkeypatch):
    from examples.shared import hosted

    case = CASES["jobsearch"]
    module = importlib.import_module(case.module)
    client = Mock()
    ids = {name: "field_" + name for name, _kind, _description in module.CUSTOM_FIELDS}
    monkeypatch.setattr(hosted, "_field_ids", lambda *_args: ids)
    fields = list(dict.fromkeys([*case.system_fields, *ids.values()]))
    client.schemas.list.return_value = [
        {"schemaId": "schema", "name": case.schema_name, "fieldIds": fields}
    ]
    client.datasets.list.return_value = [
        {
            "datasetId": "dataset",
            "name": case.dataset_name,
            "schemaId": "schema",
            "mode": case.dataset_mode,
        }
    ]
    client.templates.list.return_value = []
    client.templates.create.side_effect = lambda name, **kw: {
        "templateId": "template_" + name,
        "name": name,
        **kw,
    }
    client.jobs.list.return_value = [
        {
            "jobId": "existing",
            "name": case.label,
            "seeds": ["https://different.example/"],
        }
    ]
    with pytest.raises(RuntimeError, match="differs from the recipe"):
        HostedCaseProvisioner(client).provision(case)
    client.jobs.archive.assert_not_called()
    client.jobs.create.assert_not_called()
    client.jobs.run.assert_not_called()


def test_hosted_provisioning_reuses_resources_and_checks_template_changes(monkeypatch):
    from examples.shared import hosted

    case = CASES["jobsearch"]
    module = importlib.import_module(case.module)
    ids = {name: "field_" + name for name, _kind, _description in module.CUSTOM_FIELDS}
    monkeypatch.setattr(hosted, "_field_ids", lambda *_args: ids)
    client = Mock()
    client.schemas.list.return_value = [
        {
            "schemaId": "schema",
            "name": case.schema_name,
            "fieldIds": list(dict.fromkeys([*case.system_fields, *ids.values()])),
        }
    ]
    client.datasets.list.return_value = [
        {
            "datasetId": "dataset",
            "name": case.dataset_name,
            "schemaId": "schema",
            "mode": case.dataset_mode,
        }
    ]
    templates, jobs = [], []
    client.templates.list.side_effect = lambda **_options: list(templates)
    client.jobs.list.side_effect = lambda: list(jobs)

    def create_template(name, *, output_schema_id, engine, mappings):
        template = {
            "templateId": f"template_{len(templates)}",
            "name": name,
            "outputSchemaId": output_schema_id,
            "engine": engine,
            "mappings": mappings,
        }
        templates.append(template)
        return template

    def create_job(name, **options):
        job = {
            "jobId": "job",
            "name": name,
            "seeds": options["seeds"],
            "datasetId": options["dataset_id"],
            "scope": options["scope"],
            "politeness": options["politeness"],
            "templateStack": [
                {
                    "templateId": entry["template_id"],
                    "scope": {
                        "hosts": entry["hosts"],
                        "urlPatterns": entry["url_patterns"],
                    },
                }
                for entry in options["template_stack"]
            ],
        }
        jobs.append(job)
        return job

    client.templates.create.side_effect = create_template
    client.jobs.create.side_effect = create_job
    provisioner = HostedCaseProvisioner(client)
    first = provisioner.provision(case, cron="7 * * * *")
    count = len(templates)
    assert provisioner.provision(case, cron="7 * * * *") == first
    assert len(templates) == count
    client.jobs.create.assert_called_once()
    client.schemas.create.assert_not_called()
    client.datasets.create.assert_not_called()
    client.jobs.run.assert_not_called()
    client.jobs.archive.assert_not_called()
    client.schedules.set.assert_called_with("job", "7 * * * *", timezone="UTC")
    templates[0]["engine"] = "meta" if templates[0]["engine"] != "meta" else "css"
    with pytest.raises(RuntimeError, match="template .* differs from the recipe"):
        provisioner.provision(case)


def test_recipe_validator_checks_scope_and_rejects_literal_only_matches():
    source = {
        "hosts": ["sample.example"],
        "url_patterns": ["/articles/*"],
        "templates": [
            {
                "engine": "css",
                "mappings": {"title": "h1", "publisher": "literal:Publisher"},
            },
        ],
    }
    validator = RecipeValidator()
    assert validator.check(
        source, "https://sample.example/articles/one", "<h1>News</h1>"
    ).matched
    assert not validator.check(
        source, "https://sample.example/articles/one", "<p>Empty</p>"
    ).matched
    assert not validator.check(
        source, "https://foreign.example/articles/one", "<h1>News</h1>"
    ).matched


def test_governed_sampler_respects_robots_without_requesting_product():
    from datetime import datetime, timezone

    class DeniedFetcher:
        def __init__(self):
            self.calls = []

        async def fetch(self, url, *, user_agent):
            self.calls.append(url)
            return FetchResult(
                url=url,
                final_url=url,
                status=200,
                headers={},
                body="User-agent: *\nDisallow: /\n",
                error=None,
                fetched_at=datetime.now(timezone.utc),
            )

    fetcher = DeniedFetcher()
    with pytest.raises(ValueError, match="no allowed successful"):
        GovernedSampleReader(
            "ContactCrawler/1 (+https://operator.example/contact)", fetcher=fetcher
        ).read(EXAMPLE_URL)
    assert fetcher.calls == ["https://quickstart.example/robots.txt"]


def test_empty_saved_sample_validation_is_inconclusive(tmp_path, capsys):
    from examples.shared.validation import main

    assert main("jobsearch", ["--saved-dir", str(tmp_path)]) == 2
    assert "checked=0" in capsys.readouterr().out


def test_live_cli_guard_runs_before_workspace_creation(tmp_path, monkeypatch):
    from examples.shared.cli import main_local

    monkeypatch.delenv("PULSECRAWL_USER_AGENT", raising=False)
    root = tmp_path / "must-not-exist"
    with pytest.raises(SystemExit) as error:
        main_local(argv=["--case", "news/stocks", "--run", "--workspace", str(root)])
    assert error.value.code == 2
    assert not root.exists()


@pytest.mark.parametrize(
    "value", [None, "", " ", "Crawler/no-contact", "Crawler\nhttps://contact.example"]
)
def test_invalid_operator_identification_is_rejected(value):
    from examples.shared.safety import operator_user_agent

    with pytest.raises(ValueError, match="operator"):
        operator_user_agent(value)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_sample_timeout_must_be_finite_and_positive(timeout):
    with pytest.raises(ValueError, match="finite and positive"):
        GovernedSampleReader(
            "Crawler (+https://operator.example/contact)", timeout=timeout
        )


def test_governed_sampler_captures_fixture_without_archiving(tmp_path):
    reader = GovernedSampleReader(
        "Crawler (+https://operator.example/contact)", fetcher=FixtureFetcher()
    )
    final_url, body = reader.read(EXAMPLE_URL)
    assert final_url == EXAMPLE_URL
    assert "Hello PulseCrawl" in body
    assert list(tmp_path.iterdir()) == []


def test_saved_recipe_mapping_validation_can_pass_without_network(tmp_path):
    from examples.shared.validation import main

    (tmp_path / "openai.html").write_text(
        '<script type="application/ld+json">'
        '{"@type":"JobPosting","title":"Research Engineer",'
        '"description":"Build systems","hiringOrganization":{"name":"OpenAI"}}'
        "</script>",
        encoding="utf-8",
    )
    assert main("jobsearch", ["--saved-dir", str(tmp_path), "--source", "openai"]) == 0
