"""Offline recipe checks, with explicit governed sampling for live inputs."""

import argparse
import asyncio
from dataclasses import dataclass
import importlib
import math
import os
from pathlib import Path
import re

from pulsecrawl.adapters.inbound.python.ephemeral import crawl as async_crawl
from pulsecrawl.adapters.outbound.html.extraction import HtmlExtractorRegistry
from pulsecrawl.domain.crawling.model import TemplateSpec
from pulsecrawl.domain.crawling.urls import template_scope_matches

from .catalog import CASES
from .recipes import normalize
from .safety import operator_user_agent


class _PageCapture:
    def __init__(self):
        self.pages = []

    async def save(self, _hashed, snapshot):
        self.pages.append(snapshot)


class GovernedSampleReader:
    """Use the real crawler for robots, redirects, pacing and network safety."""

    def __init__(self, user_agent, *, timeout=30.0, fetcher=None):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        self.user_agent = operator_user_agent(user_agent)
        self.timeout, self.fetcher = timeout, fetcher

    async def _read(self, url):
        capture = _PageCapture()
        await asyncio.wait_for(
            async_crawl(
                seeds=[url],
                engine="meta",
                mappings={"title": "<title>"},
                fields=[{"fieldId": "title", "name": "title", "type": "string"}],
                scope={"maxUrlsPerExecution": 6, "maxDepth": 0},
                politeness={
                    "respectRobotsTxt": True,
                    "requestsPerSecond": 1.0,
                    "userAgent": self.user_agent,
                },
                store_raw_pages=True,
                page_sink=capture,
                fetcher=self.fetcher,
            ),
            timeout=self.timeout,
        )
        pages = [
            page for page in capture.pages if 200 <= page.status < 300 and page.body
        ]
        if not pages:
            raise ValueError(
                "no allowed successful HTML sample (check robots, redirects and HTTP outcome)"
            )
        return pages[-1].final_url, pages[-1].body

    def read(self, url):
        return asyncio.run(self._read(url))


@dataclass(frozen=True)
class RecipeCheck:
    matched_templates: int
    checked_templates: int

    @property
    def matched(self):
        return self.matched_templates > 0


class RecipeValidator:
    def __init__(self, registry=None):
        self.registry = registry or HtmlExtractorRegistry()

    def check(self, source, final_url, html):
        checked = matched = 0
        for template in source["templates"]:
            hosts = template.get("hosts", source.get("hosts", ()))
            patterns = template.get("urlPatterns", source.get("url_patterns", ()))
            if not template_scope_matches(
                final_url, hosts=tuple(hosts), url_patterns=tuple(patterns)
            ):
                continue
            checked += 1
            mappings = TemplateSpec.normalize_mappings(template["mappings"])
            rows = self.registry.get_engine(template["engine"])(html, mappings)
            literal_fields = {
                key
                for key, values in mappings.items()
                if all(value.startswith("literal:") for value in values)
            }
            content = {
                key
                for row in rows
                for key, value in row.items()
                if value is not None and str(value).strip()
            } - literal_fields
            matched += bool(content)
        return RecipeCheck(matched, checked)


def _slug(source):
    value = (
        source.get("slug") or source.get("key") or source.get("name") or source["seed"]
    )
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value)).strip("-")


def main(case_key, argv=None):
    parser = argparse.ArgumentParser(
        description="Check saved HTML or explicitly sample reviewed live URLs."
    )
    parser.add_argument(
        "--saved-dir", type=Path, help="offline HTML files named <source-slug>.html"
    )
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument(
        "--list", action="store_true", help="list sample slugs without network access"
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--user-agent", default=os.environ.get("PULSECRAWL_USER_AGENT"))
    args = parser.parse_args(argv)
    case = CASES[case_key]
    module = importlib.import_module(case.module)
    fields = {
        name: "fld_example_" + name
        for name, _kind, _description in module.CUSTOM_FIELDS
    }
    sources, _seeds = normalize(case, fields)
    if args.list:
        for source in sources:
            print(_slug(source))
        return 0
    if not args.saved_dir and not args.live:
        parser.error(
            "choose --saved-dir for offline validation or --live for authorized sampling"
        )
    if args.live and (not args.user_agent or args.timeout <= 0):
        parser.error("--live requires --user-agent and a positive --timeout")
    known = {_slug(source) for source in sources}
    if set(args.source) - known:
        parser.error(
            "unknown source(s): " + ", ".join(sorted(set(args.source) - known))
        )
    try:
        reader = (
            GovernedSampleReader(args.user_agent, timeout=args.timeout)
            if args.live
            else None
        )
    except ValueError as error:
        parser.error(str(error))
    validator = RecipeValidator()
    checked = failed = skipped = 0
    for source in sources:
        slug = _slug(source)
        if args.source and slug not in args.source:
            continue
        url = source.get("sample_url") or source.get("sampleUrl") or source["seed"]
        saved = args.saved_dir / (slug + ".html") if args.saved_dir else None
        if saved and saved.is_file():
            html = saved.read_text(encoding="utf-8")
            final_url = url
        elif reader:
            try:
                final_url, html = reader.read(url)
            except (ValueError, OSError, TimeoutError) as error:
                skipped += 1
                print(f"SKIP {slug}: {error}")
                continue
        else:
            skipped += 1
            print(f"SKIP {slug}: no saved sample")
            continue
        report = validator.check(source, final_url, html)
        checked += 1
        failed += not report.matched
        print(
            f"{'PASS' if report.matched else 'FAIL'} {slug}: "
            f"{report.matched_templates}/{report.checked_templates} applicable templates matched"
        )
    print(f"SUMMARY checked={checked} failed={failed} skipped={skipped}")
    # An all-skipped survey is inconclusive, never a successful validation.
    return 1 if failed else (0 if checked else 2)
