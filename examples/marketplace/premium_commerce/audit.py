"""Explicit opt-in, robots-only source audit. Never requests product pages.

Remote comments, agents.md links, and other text are untrusted data: this
module neither executes them nor follows their instructions or URLs.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from pulsecrawl.adapters.outbound.http.fetcher import AiohttpFetcher

from .recipes import BY_SLUG, SOURCES, Source


def conservative_robots_check(text: str, sample_url: str, user_agent: str) -> bool:
    """Conservative guard, not a complete RFC 9309 parser.

    Python's RobotFileParser does not implement '*' path patterns. In addition
    to its UA decision, refuse any matching disallow from any group. This can
    over-restrict an otherwise allowed UA, but cannot use a wildcard parsing
    gap to declare the sample eligible. It deliberately ignores exceptions.
    """
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    if not parser.can_fetch(user_agent, sample_url):
        return False
    parts = urlsplit(sample_url)
    target = parts.path + ("?" + parts.query if parts.query else "")
    for line in text.splitlines():
        key, _, raw = line.split("#", 1)[0].partition(":")
        pattern = raw.strip()
        if key.strip().lower() != "disallow" or not pattern:
            continue
        anchored = pattern.endswith("$")
        pattern = pattern[:-1] if anchored else pattern
        regex = "^" + ".*".join(re.escape(part) for part in pattern.split("*"))
        if re.search(regex + ("$" if anchored else ""), target):
            return False
    return True


async def audit_robots(
    sources: tuple[Source, ...], user_agent: str, *, fetcher=None
) -> dict:
    if not 1 <= len(sources) <= 10 or len({source.slug for source in sources}) != len(
        sources
    ):
        raise ValueError("audit needs one to ten distinct selected sources")
    if any(BY_SLUG.get(source.slug) != source for source in sources):
        raise ValueError("audit only supports the selected official origins")
    if not user_agent.startswith("PulseCrawl") or not re.search(
        r"(?:https://|mailto:)", user_agent
    ):
        raise ValueError(
            "identify PulseCrawl and include a real public contact URL or mailto address"
        )
    own_fetcher = fetcher is None
    http = fetcher or AiohttpFetcher(
        retries=1,
        timeout_s=10,
        max_body_bytes=512 * 1024,
        accepted_content_types=None,
        allow_redirects=False,
    )
    checks = []
    try:
        for index, source in enumerate(sources):
            if index and own_fetcher:
                await asyncio.sleep(2)
            url = f"https://{source.host}/robots.txt"
            response = await http.fetch(url, user_agent=user_agent)
            content_type = response.headers.get(
                "Content-Type", response.headers.get("content-type", "")
            )
            readable = (
                response.status == 200
                and response.body is not None
                and not response.body_truncated
                and "text/plain" in content_type.lower()
            )
            text = response.body if readable else None
            checks.append(
                {
                    "source": source.slug,
                    "robotsUrl": url,
                    "status": response.status,
                    "error": response.error,
                    "bytes": response.body_bytes,
                    "contentType": content_type,
                    "sha256": hashlib.sha256(text.encode()).hexdigest()
                    if text is not None
                    else None,
                    "sampleUrl": source.sample_url,
                    "conservativelyEligible": conservative_robots_check(
                        text, source.sample_url, user_agent
                    )
                    if text is not None
                    else False,
                    "productRequests": 0,
                    "liveStatus": "disabled-provisional",
                }
            )
    finally:
        if own_fetcher:
            await http.close()
    return {
        "kind": "robots-only-audit-not-product-validation",
        "checkedAtUtc": datetime.now(timezone.utc).isoformat(),
        "userAgent": user_agent,
        "physicalRequestCap": len(sources),
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--network",
        action="store_true",
        help="explicitly authorize up to ten robots requests",
    )
    parser.add_argument("--site", choices=["all", *BY_SLUG], default="all")
    parser.add_argument("--user-agent", required=True)
    args = parser.parse_args()
    if not args.network:
        parser.error("pass --network for this opt-in robots-only audit")
    sources = SOURCES if args.site == "all" else (BY_SLUG[args.site],)
    print(json.dumps(asyncio.run(audit_robots(sources, args.user_agent)), indent=2))


if __name__ == "__main__":
    main()
