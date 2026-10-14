"""Save this file anywhere; install pulsecrawl from PyPI first.

No network unless --live is supplied with --url and --user-agent.
Review authorization, site terms, and robots policies before live use.
"""

import argparse
import json
import re

from pulsecrawl import crawl


def run(url, user_agent):
    if (
        not isinstance(user_agent, str)
        or len(user_agent) > 4096
        or "\r" in user_agent
        or "\n" in user_agent
        or not re.search(r"(?:https://|mailto:)[^\s)]+", user_agent)
    ):
        raise ValueError("provide a user agent with your working https:// or mailto: contact")
    return crawl(
        seeds=[url],
        engine="meta",
        mappings={"title": ["og:title", "<title>"]},
        fields=[{"fieldId": "title", "name": "title", "type": "string"}],
        scope={"maxUrlsPerExecution": 1, "maxDepth": 0},
        politeness={
            "respectRobotsTxt": True,
            "requestsPerSecond": 1.0,
            "userAgent": user_agent.strip(),
        },
        store_raw_pages=False,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="explicitly allow HTTP requests")
    parser.add_argument("--url", help="a URL you are authorized to crawl")
    parser.add_argument("--user-agent", help="identify yourself with an operator contact")
    args = parser.parse_args(argv)
    if not args.live:
        if args.url or args.user_agent:
            parser.error("--url and --user-agent require --live")
        parser.print_help()
        return
    if not args.url or not args.user_agent:
        parser.error("--live requires --url and --user-agent")
    try:
        result = run(args.url, args.user_agent)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps({"records": result.records, "stats": result.stats}, indent=2))


if __name__ == "__main__":
    main()
