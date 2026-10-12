"""Run with: python -m marketplace.premium_commerce.local --workspace ./commerce-demo"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pulsecrawl import Workspace

from .controlled import ControlledFetcher, OBSERVATIONS, product_html
from .recipes import (
    CUSTOM_FIELDS,
    FICTIONAL_SOURCES as SOURCES,
    build_recipes,
    field_ids,
)


HISTORY_SQL = """
SELECT store, _source_url, color, size, currency, _execution_id,
       _crawled_at, current_price,
       current_price - lag(current_price) OVER (
           PARTITION BY _source_url, sku, offer_sku, color, size, currency ORDER BY _crawled_at
       ) AS price_change
FROM dataset
WHERE current_price IS NOT NULL AND currency IS NOT NULL
      AND sku IS NOT NULL AND color IS NOT NULL AND size IS NOT NULL
ORDER BY _source_url, _crawled_at
"""


def provision(workspace: Workspace) -> dict[str, Any]:
    """Author one explicit local dataset/job; existing examples are untouched."""
    ids = field_ids()
    dataset = workspace.datasets.create(
        "premium commerce - controlled price history",
        mode="append_all",
        fields=[
            {"fieldId": ids[name], "name": name, "type": kind}
            for name, kind, _ in CUSTOM_FIELDS
        ],
    )
    job = workspace.jobs.create(
        "premium commerce - controlled two executions",
        seeds=[source.sample_url for source in SOURCES],
        dataset_id=dataset["datasetId"],
        templates=[
            entry
            for recipe in build_recipes(sources=SOURCES)
            for entry in recipe["templateStack"]
        ],
        scope={
            "sameDomainOnly": True,
            "maxDepth": 0,
            "maxUrlsPerExecution": 10,
            "maxUrlsTotal": 20,
            "includePatterns": ["^" + re.escape(s.sample_url) + "$" for s in SOURCES],
        },
        politeness={
            "respectRobotsTxt": True,
            "requestsPerSecond": 1000,
            "userAgent": "PulseCrawlControlledDemo/0.1 (offline; no network)",
        },
        store_raw_pages=False,
    )
    return {"dataset": dataset, "job": job}


def run_demo(root: Path) -> dict[str, Any]:
    """Execute the real SQLite/Parquet/manifest path, with synthetic HTTP input."""
    root = root.resolve()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError(
            "choose a fresh workspace; this demonstration never overwrites an existing one"
        )
    with Workspace.init(root, name="Controlled premium-commerce example") as workspace:
        provisioned = provision(workspace)
        dataset_id = provisioned["dataset"]["datasetId"]
        executions = []
        input_hashes = []
        for index in (0, 1):
            fetcher = ControlledFetcher(index)
            result = workspace.jobs.run(provisioned["job"]["jobId"], fetcher=fetcher)
            if (
                result["status"] != "succeeded"
                or result["stats"]["materializedRows"] != 10
            ):
                raise RuntimeError(
                    f"controlled execution failed expected checks: {result}"
                )
            executions.append(
                {
                    "executionId": result["executionId"],
                    "status": result["status"],
                    "materializedRows": result["stats"]["materializedRows"],
                    "fixtureFetchCalls": len(fetcher.calls),
                }
            )
            input_hashes.extend(
                {
                    "source": source.slug,
                    "observation": index + 1,
                    "observedAt": OBSERVATIONS[index].isoformat(),
                    "sha256": hashlib.sha256(
                        product_html(source, index).encode()
                    ).hexdigest(),
                }
                for source in SOURCES
            )
        history = workspace.datasets.query(dataset_id, HISTORY_SQL)
        version_counts = [
            workspace.datasets.query(
                dataset_id, "SELECT count(*) FROM dataset", version=version
            )["rows"][0][0]
            for version in (1, 2)
        ]
        changes = [row[-1] for row in history["rows"] if row[-1] is not None]
        if version_counts != [10, 20] or changes != [-21.0] * 10:
            raise RuntimeError(
                "controlled price-history or pinned-version oracle failed"
            )
        return {
            "kind": "controlled-local-demonstration-not-live-evidence",
            "datasetId": dataset_id,
            "workspace": str(root),
            "executions": executions,
            "versionRowCounts": version_counts,
            "inputHashes": input_hashes,
            "query": HISTORY_SQL,
            "history": history,
            "checks": {
                "tenScopes": True,
                "twoCommittedVersions": True,
                "twentyObservations": True,
                "tenSyntheticPriceChanges": True,
            },
        }


def portable_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Stable checked projection: generated UUIDs and filesystem paths omitted."""
    observations = []
    for source in SOURCES:
        rows = [row for row in report["history"]["rows"] if row[1] == source.sample_url]
        observations.append(
            {
                "source": source.slug,
                "prices": [row[-2] for row in rows],
                "currency": "USD",
                "priceChange": rows[-1][-1],
            }
        )
    return {
        "kind": report["kind"],
        "versionRowCounts": report["versionRowCounts"],
        "fixtureFetchCalls": [
            item["fixtureFetchCalls"] for item in report["executions"]
        ],
        "checks": report["checks"],
        "observations": observations,
        "inputHashes": report["inputHashes"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("./commerce-demo"))
    parser.add_argument(
        "--live",
        action="store_true",
        help="reserved; provisional integrations are disabled",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="print stable checked projection instead of full query output",
    )
    args = parser.parse_args()
    if args.live:
        parser.error(
            "live integrations are disabled: resolve each site's policy/permission and validate markup first"
        )
    report = run_demo(args.workspace)
    print(
        json.dumps(
            portable_summary(report) if args.summary else report, indent=2, default=str
        )
    )


if __name__ == "__main__":
    main()
