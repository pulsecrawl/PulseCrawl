"""Vendor-neutral external-agent template authoring example.

Replace ``external_agent`` with a person, local model, or ordinary-code adapter.
PulseCrawl never invokes that component during scheduled extraction.
"""

from collections.abc import Callable, Sequence
from typing import Any

from pulsecrawl import Workspace


def author_template(
    workspace: Workspace,
    *,
    job_id: str,
    schema_id: str,
    external_agent: Callable[[Sequence[dict[str, Any]]], Sequence[dict[str, Any]]],
) -> dict[str, Any]:
    sample = workspace.authoring.sample(job_id, max_pages=20, max_depth=2)
    # inspect() returns structure-only dictionaries by default.
    inspections = [workspace.authoring.inspect(page) for page in sample["pages"]]
    proposed = external_agent(inspections)
    draft = workspace.authoring.create_draft(
        "Agent-proposed template",
        output_schema_id=schema_id,
        templates=proposed,
        source_job_id=job_id,
    )
    return {
        "draftId": draft.draft_id,
        "version": draft.version,
        "sampleExecutionId": sample["execution"]["executionId"],
        "nextStep": "add positive and negative pages, then call authoring.validate",
    }


def deterministic_example_agent(
    _inspections: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Example proposal only. It has no network, secrets, or approval authority."""
    return [
        {
            "engine": "jsonld",
            "hosts": ["publisher.example"],
            "url_patterns": ["/articles/*"],
            "mappings": {
                "fld_title": "Article.headline",
                "fld_published_at": "Article.datePublished",
                "fld_url": "Article.url",
            },
        }
    ]
