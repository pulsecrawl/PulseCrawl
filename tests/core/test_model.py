import math

import pytest

from pulsecrawl.core.model import ExecutionIntent, Politeness, Scope


@pytest.mark.parametrize("value", [0, -1, math.inf, math.nan, 1001])
def test_politeness_rejects_unsafe_rates(value):
    with pytest.raises(ValueError, match="finite"):
        Politeness(requests_per_second=value)


def test_scope_rejects_excessive_bounds():
    with pytest.raises(ValueError, match="max_depth"):
        Scope(max_depth=101)
    with pytest.raises(ValueError, match="max_pages"):
        Scope(max_pages=1_000_001)
    with pytest.raises(ValueError, match="patterns"):
        Scope(include_patterns=("x" * 2049,))


def test_system_template_scope_is_preserved_from_message_intent():
    intent = ExecutionIntent.from_message_intent(
        execution_id="exec_test",
        org_id="org_test",
        job_id="job_test",
        intent={
            "seeds": ["https://news.example/"],
            "datasetId": "ds_test",
            "templateStack": [{
                "templateId": "tmpl_authored",
                "engine": "css",
                "mappings": {"fld_title": "h1"},
            }],
            "systemTemplates": [{
                "templateId": "tmpl_system",
                "engine": "meta",
                "mappings": {"fld_title": "og:title"},
                "scope": {
                    "hosts": ["news.example"],
                    "urlPatterns": ["/articles/*"],
                },
            }],
            "schema": {
                "schemaId": "schema_test",
                "fields": [{"fieldId": "fld_title", "name": "title", "type": "string"}],
            },
        },
    )
    scope = intent.system_templates[0].scope
    assert scope is not None
    assert scope.hosts == ("news.example",)
    assert scope.url_patterns == ("/articles/*",)
