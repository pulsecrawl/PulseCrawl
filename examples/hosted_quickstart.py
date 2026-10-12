"""Hosted plan by default; --apply creates resources, --run starts a crawl.

Set PULSECRAWL_API_KEY and PULSECRAWL_BASE_URL before --apply. Use a reviewed
URL and operator-contact user agent. Nothing runs on import.
"""

import argparse
import os
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulsecrawl import PulseCrawl
from examples.shared.safety import operator_user_agent


def provision(client, *, url, user_agent, run=False):
    user_agent = operator_user_agent(user_agent)
    templates = client.templates.list(origin="system")
    template = next(
        (item for item in templates if item["templateId"] == "tmpl_sys_meta_page"), None
    )
    if template is None:
        raise ValueError(
            "this deployment must seed the system meta-page template first"
        )
    dataset = client.datasets.create(
        "quickstart pages", schema_id=template["outputSchemaId"]
    )
    job = client.jobs.create(
        "quickstart crawl",
        seeds=[url],
        template_id=template["templateId"],
        dataset_id=dataset["datasetId"],
        scope={"maxUrlsPerExecution": 5, "maxUrlsTotal": 5, "maxDepth": 0},
        politeness={
            "respectRobotsTxt": True,
            "requestsPerSecond": 1.0,
            "userAgent": user_agent,
        },
    )
    execution = None
    if run:
        started = client.jobs.run(job["jobId"])
        execution = client.executions.wait(started["executionId"], timeout_s=300)
    return {"dataset": dataset, "job": job, "execution": execution}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="create a hosted dataset and job"
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="start and wait for a live crawl; requires --apply",
    )
    parser.add_argument("--url")
    parser.add_argument("--user-agent", default=os.environ.get("PULSECRAWL_USER_AGENT"))
    args = parser.parse_args(argv)
    if args.run and not args.apply:
        parser.error("--run requires --apply")
    if not args.apply:
        print(
            "Plan only: select the system meta-page template, create a dataset and a five-page job."
        )
        print("Use --apply --url URL --user-agent CONTACT; add --run to execute it.")
        return
    api_key, base_url = (
        os.environ.get("PULSECRAWL_API_KEY"),
        os.environ.get("PULSECRAWL_BASE_URL"),
    )
    if not api_key or not base_url:
        parser.error("set PULSECRAWL_API_KEY and PULSECRAWL_BASE_URL")
    if not args.url or not args.user_agent:
        parser.error("--apply requires --url and --user-agent with an operator contact")
    with PulseCrawl(api_key=api_key, base_url=base_url) as client:
        result = provision(
            client, url=args.url, user_agent=args.user_agent, run=args.run
        )
        print(
            f"dataset: {result['dataset']['datasetId']}; job: {result['job']['jobId']}"
        )
        if result["execution"]:
            print(f"finished: {result['execution']['status']}")
            if result["execution"]["status"] != "succeeded":
                raise RuntimeError(
                    "hosted execution did not succeed; inspect it before rerunning"
                )
            for artifact in client.datasets.files(result["dataset"]["datasetId"]):
                print(f"download ({artifact['sizeBytes']} bytes): {artifact['url']}")


if __name__ == "__main__":
    main()
