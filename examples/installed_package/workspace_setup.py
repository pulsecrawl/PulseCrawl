"""Save this file anywhere; install 'pulsecrawl[workspace]' from PyPI first.

Run: python workspace_setup.py --workspace ./package-demo
Creates local definitions only. No network, crawling, or schedules.
"""

import argparse
import json
from pathlib import Path

from pulsecrawl import Workspace


def run(root):
    root = Path(root)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError("choose a fresh or empty workspace; existing data is never overwritten")
    with Workspace.init(root) as workspace:
        dataset = workspace.datasets.create(
            "pages",
            fields=[{"fieldId": "title", "name": "title", "type": "string"}],
        )
        return {
            "workspace": str(root),
            "datasetId": dataset["datasetId"],
            "valid": workspace.validate()["valid"],
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.workspace), indent=2))


if __name__ == "__main__":
    main()
