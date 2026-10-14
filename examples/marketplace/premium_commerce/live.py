"""Opt-in real-website exercise; no HTML archive and no synthetic fallback.

Preview from the repository root (no network):
python -m examples.marketplace.premium_commerce.live plan
The published manifest is a disabled plan, not evidence of completed crawling.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from pulsecrawl import Workspace
from pulsecrawl.adapters.outbound.http.fetcher import AiohttpFetcher
from pulsecrawl.domain.crawling.model import FetchResult
from pulsecrawl.domain.crawling.urls import normalize_url

from .audit import conservative_robots_check
from .recipes import BY_SLUG, CUSTOM_FIELDS, field_ids


DEFAULT_MANIFEST = Path(__file__).with_name("live-sources.json")
STATE_FILE = "case-study.json"
OBSERVATION_SQL = """SELECT store, _source_url, _execution_id, _crawled_at,
name, sku, offer_sku, color, size, current_price, currency, availability
FROM dataset ORDER BY _source_url, _crawled_at"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def save(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, default=str) + "\n")
    temporary.replace(path)


def load_manifest(path: Path, *, require_enabled: bool = False) -> dict:
    return validate_manifest(
        json.loads(path.read_text()), require_enabled=require_enabled
    )


def validate_manifest(data: dict, *, require_enabled: bool = False) -> dict:
    if (
        data.get("kind") != "live-end-to-end-case-study-plan"
        or data.get("recordHtml") is not False
    ):
        raise ValueError("use a live case-study manifest with recordHtml=false")
    ua = data.get("userAgent", "")
    if not ua.startswith("PulseCrawl") or not re.search(r"(?:https://|mailto:)", ua):
        raise ValueError("identify PulseCrawl and supply a public contact")
    limits = data["limits"]
    for key, lower, upper in (
        ("maxExecutions", 1, 2),
        ("maxPagesPerExecution", 1, 10),
        ("minIntervalHours", 24, 8760),
        ("requestsPerSecond", 0.01, 0.5),
    ):
        value = limits[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            or not lower <= value <= upper
        ):
            raise ValueError(f"invalid conservative bound: {key}")
    if any(
        type(limits[key]) is not int
        for key in ("maxExecutions", "maxPagesPerExecution")
    ):
        raise ValueError("execution and page bounds must be integers")
    sources = data["sources"]
    if not 1 <= len(sources) <= 10 or len({s["id"] for s in sources}) != len(sources):
        raise ValueError("choose one to ten distinct registered candidates")
    for source in sources:
        registered = BY_SLUG.get(source["id"])
        if (
            registered is None
            or source["url"] != registered.sample_url
            or source["termsUrl"] != registered.terms_url
        ):
            raise ValueError(
                "source must match a registered candidate URL and policy reference"
            )
        if type(source.get("enabled")) is not bool:
            raise ValueError("source enabled must be boolean")
        if source["enabled"]:
            review = source.get("accessReview", {})
            if (
                review.get("status") != "reviewed"
                or not str(review.get("basis") or "").strip()
            ):
                raise ValueError(
                    "enabled sources need an explicit reviewed access basis"
                )
            reviewed = datetime.fromisoformat(str(review.get("reviewedAt")))
            if reviewed.tzinfo is None or reviewed > datetime.now(timezone.utc):
                raise ValueError("reviewedAt must be a past timezone-aware timestamp")
    enabled = [source for source in sources if source["enabled"]]
    if require_enabled and not enabled:
        raise ValueError(
            "no reviewed sources enabled; published candidates are only a plan"
        )
    if len(enabled) > limits["maxPagesPerExecution"]:
        raise ValueError("page bound must cover the selected seeds")
    expected_fields = [
        {"name": name, "type": kind, "description": description}
        for name, kind, description in CUSTOM_FIELDS
    ]
    if data["fields"] != expected_fields:
        raise ValueError("use the declared nullable commerce schema")
    recipes = data["recipes"]
    if len(recipes) != len(sources) or {r["slug"] for r in recipes} != {
        s["id"] for s in sources
    }:
        raise ValueError("each candidate needs exactly one explicit template stack")
    # Templates remain editable in a reviewed manifest, but cannot expand network scope.
    if any(not recipe.get("templateStack") for recipe in recipes):
        raise ValueError("empty template stack")
    return data


def initialize(manifest: dict, root: Path) -> dict:
    validate_manifest(manifest, require_enabled=True)
    enabled = [s for s in manifest["sources"] if s["enabled"]]
    if not enabled:
        raise ValueError("no reviewed sources enabled")
    root = root.resolve()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError("choose a fresh workspace; existing data is never overwritten")
    ids = field_ids()
    limits = manifest["limits"]
    selected = {s["id"] for s in enabled}
    with Workspace.init(root, name="Live end-to-end case study") as workspace:
        dataset = workspace.datasets.create(
            "live product observations",
            mode="append_all",
            fields=[
                {"fieldId": ids[name], "name": name, "type": kind}
                for name, kind, _ in CUSTOM_FIELDS
            ],
        )
        job = workspace.jobs.create(
            "bounded live commerce exercise",
            seeds=[s["url"] for s in enabled],
            dataset_id=dataset["datasetId"],
            templates=[
                t
                for r in manifest["recipes"]
                if r["slug"] in selected
                for t in r["templateStack"]
            ],
            scope={
                "sameDomainOnly": True,
                "maxDepth": 0,
                "maxUrlsPerExecution": limits["maxPagesPerExecution"],
                "maxUrlsTotal": limits["maxPagesPerExecution"]
                * limits["maxExecutions"],
                "includePatterns": [
                    "^" + re.escape(normalize_url(s["url"])) + "$" for s in enabled
                ],
            },
            politeness={
                "respectRobotsTxt": True,
                "requestsPerSecond": limits["requestsPerSecond"],
                "userAgent": manifest["userAgent"],
            },
            store_raw_pages=False,
        )
        state = {
            "kind": "live-end-to-end-case-study",
            "createdAt": now(),
            "manifest": manifest,
            "manifestSha256": digest(manifest),
            "jobId": job["jobId"],
            "datasetId": dataset["datasetId"],
            "jobSha256": digest(workspace.jobs.get(job["jobId"])),
            "runs": [],
            "notes": [],
        }
        save(root / STATE_FILE, state)
    return {
        "status": "configured-not-run",
        "enabledSources": len(enabled),
        "networkRequests": 0,
    }


class ObservedFetcher:
    """Real, bounded HTTP with fresh conservative robots checks on every run.

    Exact seed URLs only. Request metadata is retained, response bodies are not.
    The extra guard can over-restrict rules; it is not a full RFC 9309 parser.
    """

    def __init__(self, manifest: dict):
        self.ua = manifest["userAgent"]
        self.urls = {
            normalize_url(s["url"]) for s in manifest["sources"] if s["enabled"]
        }
        self.robots_urls = {
            f"https://{urlsplit(url).netloc}/robots.txt" for url in self.urls
        }
        self.interval = 1 / manifest["limits"]["requestsPerSecond"]
        self.cap = 2 * len(
            self.urls
        )  # One robots and one product request per candidate.
        self.events: list[dict] = []
        self.refusals: list[dict] = []
        self.robots: dict[str, FetchResult] = {}
        self.last: dict[str, float] = {}
        self.product_urls: set[str] = set()

    def refused(self, url: str, reason: str) -> FetchResult:
        self.refusals.append({"url": url, "reason": reason, "at": now()})
        return FetchResult(
            url=url,
            final_url=url,
            status=403,
            headers={},
            body=None,
            error=reason,
            fetched_at=datetime.now(timezone.utc),
        )

    async def request(self, url: str, *, interval: float) -> FetchResult:
        if len(self.events) >= self.cap:
            return self.refused(url, "physical-request-cap")
        host = urlsplit(url).netloc
        await asyncio.sleep(
            max(0, self.last.get(host, 0) + interval - time.monotonic())
        )
        self.last[host] = time.monotonic()
        event = {"url": url, "startedAt": now(), "status": None, "error": True}
        self.events.append(event)  # Counts even a failed transport attempt.
        http = AiohttpFetcher(
            retries=1,
            timeout_s=20,
            max_body_bytes=2 * 1024 * 1024,
            accepted_content_types=None,
            allow_redirects=False,
            allow_private_networks=False,
        )
        try:
            response = await http.fetch(url, user_agent=self.ua)
        finally:
            await http.close()
        event.update(
            {
                "finishedAt": now(),
                "status": response.status,
                "error": bool(response.error),
                "bodyBytes": response.body_bytes,
                "truncated": response.body_truncated,
                "sha256": hashlib.sha256(response.body.encode()).hexdigest()
                if response.body is not None
                else None,
            }
        )
        return response

    async def fetch(self, url: str, *, user_agent: str) -> FetchResult:
        if user_agent != self.ua:
            return self.refused(url, "unexpected-user-agent")
        if url in self.robots_urls:
            if url not in self.robots:
                self.robots[url] = await self.request(url, interval=self.interval)
            return self.robots[url]
        if url not in self.urls:
            return self.refused(url, "outside-exact-seeds")
        if url in self.product_urls:
            return self.refused(url, "duplicate-product-attempt")
        robots_url = f"https://{urlsplit(url).netloc}/robots.txt"
        policy = await self.fetch(robots_url, user_agent=user_agent)
        content_type = {k.lower(): v for k, v in policy.headers.items()}.get(
            "content-type", ""
        )
        if (
            policy.status != 200
            or policy.error
            or policy.body is None
            or policy.body_truncated
            or "text/plain" not in content_type.lower()
            or not conservative_robots_check(policy.body, url, self.ua)
        ):
            return self.refused(url, "robots-preflight-denied-or-unreadable")
        parser = RobotFileParser()
        parser.parse(policy.body.splitlines())
        delay = max(self.interval, float(parser.crawl_delay(self.ua) or 0))
        rate = parser.request_rate(self.ua)
        if rate and rate.requests:
            delay = max(delay, rate.seconds / rate.requests)
        self.product_urls.add(url)
        return await self.request(url, interval=delay)


def execute(manifest: dict, root: Path, *, network: bool) -> dict:
    if not network:
        raise ValueError("pass --network explicitly; no requests have been made")
    validate_manifest(manifest, require_enabled=True)
    root = root.resolve()
    lock = root / "case-study.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ValueError(
            "exercise locked; investigate an active/interrupted run before removing its lock"
        ) from error
    os.close(fd)
    try:
        state = json.loads((root / STATE_FILE).read_text())
        if digest(manifest) != state["manifestSha256"]:
            raise ValueError(
                "configuration changed; retain the old evidence and initialize a fresh repair workspace"
            )
        limits = manifest["limits"]
        if len(state["runs"]) >= limits["maxExecutions"]:
            raise ValueError(
                "manual execution cap reached (including interrupted attempts)"
            )
        if state["runs"]:
            elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(
                state["runs"][-1]["startedAt"]
            )
            if elapsed.total_seconds() < limits["minIntervalHours"] * 3600:
                raise ValueError("minimum repeat interval has not elapsed")
        with Workspace(root) as workspace:
            if digest(workspace.jobs.get(state["jobId"])) != state["jobSha256"]:
                raise ValueError(
                    "workspace job changed; initialize a fresh repair workspace"
                )
            run = {
                "startedAt": now(),
                "status": "reserved-before-http",
                "physicalRequests": [],
                "refusals": [],
            }
            state["runs"].append(run)
            save(root / STATE_FILE, state)
            fetcher = ObservedFetcher(manifest)
            try:
                outcome = workspace.jobs.run(
                    state["jobId"], fetcher=fetcher, store_raw_pages=False
                )
                run.update(
                    {
                        "status": outcome["status"],
                        "executionId": outcome["executionId"],
                        "stats": outcome["stats"],
                    }
                )
                pointer = (
                    root
                    / "datasets"
                    / state["datasetId"]
                    / "manifests"
                    / "current.json"
                )
                run["committedVersion"] = (
                    json.loads(pointer.read_text()) if pointer.exists() else None
                )
                history = workspace.datasets.query(state["datasetId"], OBSERVATION_SQL)
                run["observations"] = history
                columns = history["columns"]
                rows = [dict(zip(columns, row)) for row in history["rows"]]
                current = [
                    row
                    for row in rows
                    if row["_execution_id"] == outcome["executionId"]
                ]
                run["observationChecks"] = {
                    "rows": len(current),
                    "namedProducts": sum(bool(row["name"]) for row in current),
                    "pricedProductsWithCurrency": sum(
                        row["current_price"] is not None and bool(row["currency"])
                        for row in current
                    ),
                }
            except Exception as error:
                run.update({"status": "failed", "errorType": type(error).__name__})
                raise
            finally:
                run.update(
                    {
                        "finishedAt": now(),
                        "physicalRequests": fetcher.events,
                        "refusals": fetcher.refusals,
                    }
                )
                save(root / STATE_FILE, state)
            return run
    finally:
        lock.unlink()


def add_note(root: Path, stage: str, text: str) -> dict:
    if not text.strip() or len(text) > 4000:
        raise ValueError(
            "note must contain 1-4000 characters; avoid personal or secret data"
        )
    lock = root / "case-study.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ValueError(
            "wait for the current execution before adding notes"
        ) from error
    os.close(fd)
    try:
        state = json.loads((root / STATE_FILE).read_text())
        note = {"at": now(), "stage": stage, "text": text}
        state["notes"].append(note)
        save(root / STATE_FILE, state)
        return note
    finally:
        lock.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "init", "run", "note"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--network", action="store_true")
    parser.add_argument(
        "--stage",
        choices=("setup", "execution", "inspection", "repeat", "query", "repair"),
    )
    parser.add_argument("--text")
    args = parser.parse_args()
    try:
        if args.command == "plan":
            manifest = load_manifest(args.manifest)
            result = {
                "status": "plan-not-evidence",
                "networkRequests": 0,
                "sources": [
                    {
                        "id": s["id"],
                        "url": s["url"],
                        "enabled": s["enabled"],
                        "accessReview": s["accessReview"]["status"],
                    }
                    for s in manifest["sources"]
                ],
            }
        else:
            if args.workspace is None:
                raise ValueError("--workspace is required")
            if args.command == "note":
                if not args.stage or not args.text:
                    raise ValueError("note requires --stage and --text")
                result = add_note(args.workspace, args.stage, args.text)
            else:
                manifest = load_manifest(args.manifest, require_enabled=True)
                result = (
                    initialize(manifest, args.workspace)
                    if args.command == "init"
                    else execute(manifest, args.workspace, network=args.network)
                )
    except (ValueError, KeyError, OSError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
