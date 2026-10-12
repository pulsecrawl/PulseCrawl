from dataclasses import replace
from datetime import datetime, timezone

import pytest

from pulsecrawl.domain.errors import WorkspaceError
from pulsecrawl.domain.executions.lifecycle import (
    BudgetReservation,
    Execution,
    freeze_intent,
)
from pulsecrawl.domain.templates.authoring import TemplateDraft
from pulsecrawl.domain.crawling.retry import retry_after_seconds
from pulsecrawl.domain.datasets.identity import normalize_url_identity
from pulsecrawl.domain.crawling.urls import normalize_url


@pytest.mark.parametrize(
    "values,expected", [((10, 100, 20, 30), 10), ((100, 100, 20, 30), 50)]
)
def test_budget_is_bounded_by_unreserved_capacity(values, expected):
    assert BudgetReservation.allocate(*values).urls == expected


@pytest.mark.parametrize("values", [(1, 10, 10, 0), (1, 10, 8, 2), (1, 10, 11, 0)])
def test_exhausted_budget_cannot_be_reserved(values):
    with pytest.raises(WorkspaceError):
        BudgetReservation.allocate(*values)


def test_execution_lifecycle_rejects_terminal_rewrites():
    Execution("e", "running").require_runnable()
    Execution("e", "running").require_terminal_transition("succeeded")
    Execution("e", "succeeded").require_terminal_transition("succeeded")
    with pytest.raises(WorkspaceError):
        Execution("e", "failed").require_runnable()
    with pytest.raises(WorkspaceError):
        Execution("e", "succeeded").require_terminal_transition("failed")
    with pytest.raises(ValueError):
        Execution("e", "running").require_terminal_transition("queued")


def test_freezing_intent_never_expands_sampling_limits():
    job = dict(
        seeds=["https://example.com"],
        datasetId="d",
        templates=[{}],
        systemTemplates=[],
        schema={},
        scope={"maxUrlsPerExecution": 100, "maxDepth": 3},
        politeness={},
        storeRawPages=False,
    )
    intent, reservation = freeze_intent(
        job, 20, max_urls_per_execution=200, max_depth=30
    )
    assert reservation == 20
    assert intent["scope"]["maxDepth"] == 3
    with pytest.raises(ValueError):
        freeze_intent(job, 20, max_urls_per_execution=0)
    with pytest.raises(ValueError):
        freeze_intent(job, 20, max_depth=-1)


def draft():
    return TemplateDraft(
        "draft_a", "A", "s", 1, ({"engine": "css"},), "draft", "2026-01-01"
    )


def test_draft_approval_requires_latest_passing_validation_and_actor():
    original = draft()
    failed = original.with_validation({"passed": False, "validationId": "bad"})
    assert failed.status == "draft"
    validated = original.with_validation({"passed": True, "validationId": "v1"})
    with pytest.raises(ValueError, match="validated"):
        original.approve("v1", "reviewer", "now")
    with pytest.raises(ValueError, match="passing"):
        replace(failed, status="validated").approve("bad", "reviewer", "now")
    with pytest.raises(ValueError, match="latest"):
        validated.approve("v0", "reviewer", "now")
    with pytest.raises(ValueError, match="actor"):
        validated.approve("v1", " ", "now")
    approved = validated.approve("v1", " reviewer ", "now")
    assert approved.approved_by == "reviewer"
    with pytest.raises(ValueError, match="immutable"):
        approved.with_validation({"passed": True})
    with pytest.raises(ValueError, match="every"):
        approved.promote(())
    with pytest.raises(ValueError, match="approved"):
        original.promote(("t",))
    assert approved.promote(("t",)).promoted_template_ids == ("t",)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, 2),
        ("NaN", 2),
        ("garbage", 2),
        ("900", 300),
        ("-1", 0),
        ("Thu, 01 Jan 2026 00:00:10 GMT", 10),
        ("Thu, 01 Jan 2026 00:00:10", 10),
    ],
)
def test_retry_after_policy_is_deterministic_and_bounded(value, expected):
    assert (
        retry_after_seconds(value, 1, datetime(2026, 1, 1, tzinfo=timezone.utc))
        == expected
    )


def test_crawl_and_dataset_url_semantics_are_deliberately_distinct():
    url = "https://EXAMPLE.com/?b=2&a=1"
    assert normalize_url(url).endswith("?b=2&a=1")
    assert normalize_url_identity(url).endswith("?a=1&b=2")
