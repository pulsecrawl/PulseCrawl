# PulseCrawl

**[GitHub repository](https://github.com/pulsecrawl/PulseCrawl)**

PulseCrawl is a local open-source Python crawler and structured extraction SDK.
One Python distribution supports in-memory crawling and durable local workspaces.
Run on your own machine with no account required. Requires Python 3.11 or newer.

## Installation

```bash
python -m pip install 'pulsecrawl[workspace]'
```

No repository clone is needed. For in-memory crawling only, use
`python -m pip install pulsecrawl`. The `workspace` extra
adds SQLite-backed execution state, Parquet datasets, embedded DuckDB queries,
and cron scheduling. No Docker, Redis, or database server is required.

Additional extras: `sql` for DuckDB-backed local results and `dev` for
contributors.

## Quickstart (no network)

After installing the workspace extra, save this as `quickstart.py` and run
`python quickstart.py` from any directory. Choose a new workspace path:

```python
from pulsecrawl import Workspace

with Workspace.init("./my-crawls") as pc:
    dataset = pc.datasets.create(
        "pages",
        fields=[{"fieldId": "title", "name": "title", "type": "string"}],
    )
    print(dataset["datasetId"])
    print(pc.validate()["valid"])
```

This creates local definitions only; it does not start a crawl. The installed
CLI can also initialize and validate a fresh workspace:

```bash
pulsecrawl init ./cli-crawls
pulsecrawl --workspace ./cli-crawls validate
```

See the [standalone package examples](https://github.com/pulsecrawl/PulseCrawl/tree/main/examples/installed_package)
for independently runnable workspace setup and explicitly opted-in live crawling.

## Features and boundaries

- CSS, JSON-LD, and metadata extraction with URL-scoped template stacks.
- Robots checks, request pacing, bounded responses, redirect authorization,
  and private-network blocking by default.
- Portable workspaces with dataset history, SQL, compaction, and backup/restore.
- Public Python and CLI interfaces over one hexagonal crawl engine.

Before a live crawl, review authorization, site terms, and robots policies and
identify your operator with a working contact in the user agent. Safeguards do
not grant permission to scrape. The private-network opt-in must never be used
with untrusted URLs or job definitions.

Start with the [guide and public API examples](https://github.com/pulsecrawl/PulseCrawl#readme)
and [offline examples](https://github.com/pulsecrawl/PulseCrawl/tree/main/examples).
The examples are available in the source repository and source distribution,
not as modules installed by the wheel.

## Project information

PulseCrawl is alpha software; APIs and workspace compatibility may evolve.
See the [support policy](https://github.com/pulsecrawl/PulseCrawl/blob/main/SUPPORT.md)
and [changelog](https://github.com/pulsecrawl/PulseCrawl/blob/main/CHANGELOG.md).
It is licensed under [AGPL-3.0-only](https://github.com/pulsecrawl/PulseCrawl/blob/main/LICENSE).
Report vulnerabilities using the [security policy](https://github.com/pulsecrawl/PulseCrawl/security/policy),
not a public issue.
