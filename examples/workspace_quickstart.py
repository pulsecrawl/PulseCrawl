"""Offline SQLite/Parquet/SQL demonstration using the public Workspace API.

python -m examples.workspace_quickstart --workspace ./quickstart-workspace
Install the workspace extra first: pip install -e '.[workspace]'.
"""

import argparse
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulsecrawl import Workspace
from examples.shared.fixtures import EXAMPLE_URL, FIELDS, MAPPINGS, FixtureFetcher


def run(root):
    root = Path(root)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError(
            "choose a fresh or empty workspace; existing data is never overwritten"
        )
    with Workspace.init(root) as workspace:
        dataset = workspace.datasets.create("quickstart pages", fields=FIELDS)
        job = workspace.jobs.create(
            "offline quickstart",
            seeds=[EXAMPLE_URL],
            dataset_id=dataset["datasetId"],
            templates=[{"engine": "meta", "mappings": MAPPINGS}],
            scope={"maxUrlsPerExecution": 1, "maxUrlsTotal": 1, "maxDepth": 0},
            politeness={
                "respectRobotsTxt": True,
                "userAgent": "PulseCrawlOfflineExample/0.1 (no network)",
            },
        )
        execution = workspace.jobs.run(job["jobId"], fetcher=FixtureFetcher())
        if execution["status"] != "succeeded":
            raise RuntimeError(f"offline execution failed: {execution}")
        query = workspace.datasets.query(
            dataset["datasetId"], "SELECT title, description FROM dataset"
        )
        return {
            "datasetId": dataset["datasetId"],
            "execution": execution,
            "query": query,
            "validation": workspace.validate(),
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", type=Path, default=Path("./quickstart-workspace")
    )
    args = parser.parse_args(argv)
    print(run(args.workspace))


if __name__ == "__main__":
    main()
