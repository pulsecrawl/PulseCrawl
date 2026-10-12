# PulseCrawl

PulseCrawl is a safety-governed Python crawler and structured extraction SDK.
One Python distribution supports in-memory crawling, durable local workspaces,
and an optional client for operator-hosted services. Local use needs no account
or cloud service. Requires Python 3.11 or newer.

## Installation

After a release is published to PyPI:

```bash
python -m pip install pulsecrawl
python -m pip install 'pulsecrawl[workspace]'
pulsecrawl init ./my-crawls
pulsecrawl --workspace ./my-crawls validate
```

The base install provides crawling and the HTTP client. The `workspace` extra
adds SQLite-backed execution state, Parquet datasets, embedded DuckDB queries,
and cron scheduling. No Docker, Redis, or database server is required.

Additional extras: `sql` for DuckDB-backed local results, `cloud` for optional
credential storage and workspace synchronization, and `dev` for contributors.
Hosted services are not included and have no default API endpoint.

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
