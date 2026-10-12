"""Offline by default: python -m examples.local_quickstart.

Use --live --url URL --user-agent CONTACT only after reviewing access policy.
For durable Parquet and SQL, see examples.workspace_quickstart.
"""

import argparse
import os
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulsecrawl import crawl
from examples.shared.fixtures import EXAMPLE_URL, FIELDS, MAPPINGS, FixtureFetcher
from examples.shared.safety import operator_user_agent


def run(*, url=EXAMPLE_URL, live=False, user_agent=None, fetcher=None):
    if live and not user_agent:
        raise ValueError("live crawling requires a user agent with an operator contact")
    if live:
        user_agent = operator_user_agent(user_agent)
    return crawl(
        seeds=[url],
        engine="meta",
        mappings=MAPPINGS,
        fields=FIELDS,
        scope={"maxUrlsPerExecution": 5, "maxDepth": 0},
        politeness={
            "respectRobotsTxt": True,
            "requestsPerSecond": 1.0,
            "userAgent": user_agent or "PulseCrawlOfflineExample/0.1 (no network)",
        },
        fetcher=fetcher
        if fetcher is not None
        else (None if live else FixtureFetcher()),
        store_raw_pages=False,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--url")
    parser.add_argument("--user-agent", default=os.environ.get("PULSECRAWL_USER_AGENT"))
    args = parser.parse_args(argv)
    if args.live and (not args.url or not args.user_agent):
        parser.error("--live requires --url and --user-agent with an operator contact")
    if args.url and not args.live:
        parser.error("--url requires --live; the default is a fictional offline input")
    result = run(
        url=args.url or EXAMPLE_URL, live=args.live, user_agent=args.user_agent
    )
    print(f"stats: {result.stats}")
    for record in result.records:
        print(record)


if __name__ == "__main__":
    main()
