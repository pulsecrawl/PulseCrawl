"""Contract checks for every organized multi-source hosted example."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
sys.path.insert(0, str(EXAMPLES))

from hosted_cases import CASES, _field_ids, _normalise, _scope_matches  # noqa: E402
from local_cases import provision_local_case  # noqa: E402
from pulsecrawl import Workspace


def _case_data(case):
    module = importlib.import_module(case.module)
    field_ids = {
        name: f"fld_test_{case.key.replace('/', '_')}_{name}"
        for name, _field_type, _description in module.CUSTOM_FIELDS
    }
    return _normalise(case, field_ids)


def test_all_eight_cases_have_one_twenty_source_job_recipe():
    assert set(CASES) == {
        "jobsearch",
        "news/chihuahua",
        "news/mexico",
        "news/stocks",
        "marketplace/clothes",
        "marketplace/supermarkets",
        "marketplace/mro",
        "marketplace/other_industries",
    }
    for case in CASES.values():
        sources, seeds = _case_data(case)
        assert len(sources) == 20, case.key
        assert len(seeds) >= 20, case.key
        assert len(seeds) == len(set(seeds)), case.key


def test_every_authored_template_has_a_final_url_scope_and_real_mapping():
    for case in CASES.values():
        sources, _seeds = _case_data(case)
        authored = 0
        for source in sources:
            for template in source["templates"]:
                authored += 1
                hosts = template.get("hosts", source.get("hosts"))
                patterns = template.get("urlPatterns", source.get("url_patterns"))
                assert hosts and all(host for host in hosts), (case.key, template["name"])
                assert patterns and all(pattern for pattern in patterns), (
                    case.key,
                    template["name"],
                )
                assert template["engine"] in {"jsonld", "meta", "css"}
                assert template["mappings"]
        assert authored > 0, case.key


def test_site_constants_cannot_escape_a_scoped_stack_entry():
    for case in CASES.values():
        sources, _seeds = _case_data(case)
        for source in sources:
            for template in source["templates"]:
                has_literal = any(
                    str(value).startswith("literal:")
                    for mapping in template["mappings"].values()
                    for value in (mapping if isinstance(mapping, (list, tuple)) else (mapping,))
                )
                if has_literal:
                    assert template.get("hosts", source.get("hosts"))
                    assert template.get("urlPatterns", source.get("url_patterns"))


def test_schemas_include_compatible_system_fallback_fields():
    for case in CASES.values():
        assert case.system_fields, case.key
        assert "fld_sys_url" in case.system_fields, case.key
        if case.key.startswith("news/"):
            assert "fld_sys_published_at" in case.system_fields
        if case.key.startswith("marketplace/"):
            assert "fld_sys_name" in case.system_fields


def test_examples_cover_both_dataset_write_modes():
    modes = {case.dataset_mode for case in CASES.values()}
    assert modes == {"append_all", "new_urls_only"}
    assert CASES["news/chihuahua"].dataset_mode == "new_urls_only"
    assert CASES["news/stocks"].dataset_mode == "new_urls_only"
    assert CASES["marketplace/clothes"].dataset_mode == "append_all"


def test_all_hosted_cases_use_depth_six_and_two_level_url_budgets():
    ten_million_url_cases = {
        "jobsearch",
        "news/chihuahua",
        "news/stocks",
        "marketplace/clothes",
    }
    for key, case in CASES.items():
        assert case.scope == {
            "maxUrlsPerExecution": 1_000,
            "maxUrlsTotal": 10_000_000 if key in ten_million_url_cases else 1_000_000,
            "maxDepth": 6,
        }
        assert _scope_matches(
            {
                **case.scope,
                "sameDomainOnly": True,
                "includePatterns": [],
                "excludePatterns": [],
            },
            case.scope,
        )


def test_custom_fields_reuse_compatible_selected_system_columns():
    class Fields:
        def __init__(self):
            self.created = []

        def list(self, *, origin):
            if origin == "system":
                return [
                    {"fieldId": "fld_sys_url", "name": "url", "type": "url"},
                    {"fieldId": "fld_sys_title", "name": "title", "type": "string"},
                ]
            return []

        def create(self, name, field_type, *, description):
            field = {"fieldId": f"fld_org_{name}", "name": name, "type": field_type}
            self.created.append(field)
            return field

    class Client:
        fields = Fields()

    result = _field_ids(
        Client(),
        (("title", "string", "title"), ("url", "url", "url"), ("company", "string", "company")),
        ("fld_sys_title", "fld_sys_url"),
    )
    assert result == {
        "title": "fld_sys_title",
        "url": "fld_sys_url",
        "company": "fld_org_company",
    }
    assert [field["name"] for field in Client.fields.created] == ["company"]


def test_all_cases_provision_into_one_valid_directory_workspace(tmp_path):
    with Workspace.init(tmp_path / "examples") as workspace:
        for case in CASES.values():
            result = provision_local_case(
                workspace, case, cron="4 * * * *"
            )
            assert result["sourceCount"] == 20
            assert result["templateCount"] > 0
        assert workspace.validate()["valid"] is True
        assert len(workspace.jobs.list()) == 8
        assert len(workspace.datasets.list()) == 8
        assert len(workspace.schedules.list()) == 8
