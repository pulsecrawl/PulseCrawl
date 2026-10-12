#!/usr/bin/env python3
"""Require successful full OSS CI on the exact release SHA (read-only API)."""

from __future__ import annotations

import argparse
import json
import re
import subprocess

REPOSITORY = "pulsecrawl/PulseCrawl"
WORKFLOW = ".github/workflows/oss-ci.yml"
REQUIRED_JOBS = {
    *(f"Python {version} on {system}" for version in ("3.11", "3.12", "3.13", "3.14")
      for system in ("ubuntu-latest", "macos-latest", "windows-latest")),
    "Declared minimum dependencies",
    "Rootless hardened container acceptance",
    "distribution",
    "public-boundary",
    "Release validation complete",
}


def require_successful_run(runs, sha):
    eligible = [run for run in runs if (
        run.get("head_sha") == sha and run.get("head_branch") == "main"
        and run.get("event") == "push" and run.get("path") == WORKFLOW
        and run.get("head_repository", {}).get("full_name") == REPOSITORY
    )]
    if not eligible:
        raise ValueError("no main-branch OSS CI push run for this exact SHA")
    latest = max(eligible, key=lambda run: (run["id"], run.get("run_attempt", 1)))
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise ValueError("latest OSS CI run/attempt for this SHA has not succeeded")
    return latest


def require_successful_jobs(jobs):
    for name in sorted(REQUIRED_JOBS):
        matches = [job for job in jobs if job.get("name") == name]
        if len(matches) != 1 or matches[0].get("status") != "completed" or (
            matches[0].get("conclusion") != "success"
        ):
            raise ValueError(f"required CI job missing, skipped, or unsuccessful: {name}")


def require_protected_environment(environment):
    policy = environment.get("deployment_branch_policy") or {}
    if policy != {"protected_branches": True, "custom_branch_policies": False}:
        raise ValueError("publishing environment must allow protected branches only")
    approvals = [rule for rule in environment.get("protection_rules", [])
                 if rule.get("type") == "required_reviewers"]
    if len(approvals) != 1 or not approvals[0].get("reviewers") or (
        approvals[0].get("prevent_self_review") is not True
    ):
        raise ValueError("publishing environment requires reviewers and prevention of self-review")


def api(endpoint, *parameters, paginate=False):
    command = ["gh", "api", "--method", "GET", endpoint]
    if paginate:
        command.extend(["--paginate", "--slurp"])
    for parameter in parameters:
        command.extend(["-f", parameter])
    return json.loads(subprocess.check_output(command, text=True, timeout=45))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--target", choices=["testpypi", "pypi"], required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.sha):
        parser.error("a full commit SHA is required")
    try:
        repository = api(f"repos/{REPOSITORY}")
        if repository.get("private") is not False:
            raise ValueError("the OSS source repository is not public")
        branch = api(f"repos/{REPOSITORY}/branches/main")
        if branch.get("protected") is not True:
            raise ValueError("main must be protected before publishing")
        for name in (["testpypi", "pypi"] if args.target == "pypi" else ["testpypi"]):
            require_protected_environment(api(f"repos/{REPOSITORY}/environments/{name}"))
        response = api(f"repos/{REPOSITORY}/actions/workflows/oss-ci.yml/runs",
                       f"head_sha={args.sha}", "branch=main", "event=push", "per_page=100")
        run = require_successful_run(response["workflow_runs"], args.sha)
        pages = api(f"repos/{REPOSITORY}/actions/runs/{run['id']}/jobs",
                    "filter=latest", "per_page=100", paginate=True)
        require_successful_jobs([job for page in pages for job in page["jobs"]])
    except (ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Release blocked: {error}\n")
    print(f"Full OSS CI passed for exact release SHA {args.sha}; run {run['id']}")


if __name__ == "__main__":
    main()
