#!/usr/bin/env python3
"""Run against a clean, non-editable install. Fictional input; no HTTP traffic."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from pulsecrawl import PulseCrawl, Workspace, __version__, crawl
from pulsecrawl.domain.crawling.model import FetchResult

URL = "https://release-smoke.example/page"
FIELDS = [{"fieldId": "title", "name": "title", "type": "string"}]
TEMPLATES = [{"engine": "meta", "mappings": {"title": "<title>"}}]


class FixtureFetcher:
    async def fetch(self, url, *, user_agent):
        if url == URL:
            body = "<title>Installed wheel works</title>"
        elif url == "https://release-smoke.example/robots.txt":
            body = "User-agent: *\nAllow: /\n"
        else:
            raise RuntimeError(f"unexpected fixture request: {url}")
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            body=body,
            headers={},
            error=None,
            fetched_at=datetime.now(timezone.utc),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", action="store_true")
    args = parser.parse_args()
    result = crawl(
        seeds=[URL],
        engine="meta",
        mappings={"title": "<title>"},
        fields=FIELDS,
        scope={"maxUrlsPerExecution": 1, "maxDepth": 0},
        fetcher=FixtureFetcher(),
    )
    assert (
        len(result.records) == 1
        and result.records[0]["title"] == "Installed wheel works"
    )
    assert PulseCrawl is not None
    if args.workspace:
        with tempfile.TemporaryDirectory(
            prefix="pulsecrawl-release-smoke-"
        ) as temporary:
            root = Path(temporary) / "workspace"
            with Workspace.init(root) as workspace:
                dataset = workspace.datasets.create("release smoke", fields=FIELDS)
                job = workspace.jobs.create(
                    "offline",
                    seeds=[URL],
                    dataset_id=dataset["datasetId"],
                    templates=TEMPLATES,
                    scope={"maxUrlsPerExecution": 1, "maxUrlsTotal": 1, "maxDepth": 0},
                )
                execution = workspace.jobs.run(job["jobId"], fetcher=FixtureFetcher())
                assert execution["status"] == "succeeded", execution
                result = workspace.datasets.query(
                    dataset["datasetId"], "SELECT title FROM dataset"
                )
                assert result["rows"] == [["Installed wheel works"]], result
                assert workspace.validate()["valid"]
            with Workspace(root) as reopened:
                assert reopened.validate()["valid"]
    print(
        f"Installed pulsecrawl {__version__}: {'base + workspace' if args.workspace else 'base'} offline smoke passed"
    )


if __name__ == "__main__":
    main()
