"""A tag's ancestry alone is not evidence that it passed full CI."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_ci", ROOT / "scripts/check-release-ci.py")
CI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CI)
SHA = "a" * 40


def run(**overrides):
    return {
        "id": 123, "head_sha": SHA, "head_branch": "main", "event": "push",
        "path": CI.WORKFLOW, "head_repository": {"full_name": CI.REPOSITORY},
        "status": "completed", "conclusion": "success", "run_attempt": 1,
        **overrides,
    }


def test_exact_successful_run_and_complete_jobs_pass():
    assert CI.require_successful_run([run()], SHA)["id"] == 123
    CI.require_successful_jobs([
        {"name": name, "status": "completed", "conclusion": "success"}
        for name in CI.REQUIRED_JOBS
    ])


@pytest.mark.parametrize("overrides", [
    {"head_sha": "b" * 40}, {"head_branch": "feature"}, {"event": "pull_request"},
    {"path": ".github/workflows/other.yml"}, {"head_repository": {"full_name": "fork/repo"}},
    {"status": "in_progress"}, {"conclusion": "failure"}, {"conclusion": "skipped"},
])
def test_wrong_or_unsuccessful_run_is_rejected(overrides):
    with pytest.raises(ValueError):
        CI.require_successful_run([run(**overrides)], SHA)


def test_newer_failed_attempt_cannot_be_masked_by_older_success():
    with pytest.raises(ValueError):
        CI.require_successful_run([run(), run(run_attempt=2, conclusion="failure")], SHA)


@pytest.mark.parametrize("conclusion", ["failure", "skipped", "neutral", None])
def test_every_required_job_must_succeed(conclusion):
    jobs = [{"name": name, "status": "completed", "conclusion": "success"}
            for name in CI.REQUIRED_JOBS]
    jobs[0]["conclusion"] = conclusion
    with pytest.raises(ValueError):
        CI.require_successful_jobs(jobs)


def test_missing_matrix_job_is_rejected():
    with pytest.raises(ValueError):
        CI.require_successful_jobs([])


def environment():
    return {"deployment_branch_policy": {
        "protected_branches": True, "custom_branch_policies": False,
    }, "protection_rules": [{
        "type": "required_reviewers", "prevent_self_review": True,
        "reviewers": [{"type": "Team", "reviewer": {"id": 1}}],
    }]}


def test_protected_environment_passes():
    CI.require_protected_environment(environment())


@pytest.mark.parametrize("case", ["no-policy", "no-reviewers", "self-review", "no-rules"])
def test_unprotected_environment_is_rejected(case):
    value = environment()
    if case == "no-policy":
        value["deployment_branch_policy"] = None
    elif case == "no-reviewers":
        value["protection_rules"][0]["reviewers"] = []
    elif case == "self-review":
        value["protection_rules"][0]["prevent_self_review"] = False
    else:
        value["protection_rules"] = []
    with pytest.raises(ValueError):
        CI.require_protected_environment(value)
