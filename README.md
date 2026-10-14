# PulseCrawl

A local open-source Python crawler and structured extraction SDK. Crawl in
memory or keep durable, portable workspaces on your own machine.
Local use is free and needs no account, Docker, Redis, or database server.
Requires **Python 3.11 or newer**. PulseCrawl is alpha software; see the
[support policy](SUPPORT.md) before relying on API or workspace compatibility.

## Installation

Install the published package from [PyPI](https://pypi.org/project/pulsecrawl/).
No repository clone is needed. For durable workspaces, Parquet, SQL, and schedules:

```bash
python -m pip install 'pulsecrawl[workspace]'
```

For in-memory crawling only, use `python -m pip install pulsecrawl`.
Optional extras are `sql` for querying in-memory results and `workspace` for
the complete local runtime.
Check the installed version with `python -m pip show pulsecrawl`.
Source-checkout and editable installation instructions are in
[CONTRIBUTING.md](CONTRIBUTING.md), not required for ordinary package use.

## Quickstart: create a local workspace

After installing `pulsecrawl[workspace]`, save this as `quickstart.py` in any
directory and run `python quickstart.py`. Choose a new workspace directory.
This example creates local definitions only; it does not crawl or contact a service.

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

You can also initialize and validate a fresh workspace with the installed CLI:

```bash
pulsecrawl init ./cli-crawls
pulsecrawl --workspace ./cli-crawls validate
```

The [standalone package examples](examples/README.md#standalone-package-examples-no-clone)
can each be saved on their own and run against the PyPI package. The larger
offline recipe demos are separate repository examples, not installed modules.

## Local crawling and workspaces

Crawl in memory, or use a portable workspace for durable SQLite state,
Parquet dataset versions, embedded DuckDB queries, and hourly schedules.

The following example makes live HTTP requests (including robots checks).
Before running it, review the target's access policy and replace the contact
placeholder with your own working operator contact. It needs only the base package.

```python
from pulsecrawl import crawl

result = crawl(
    seeds=["https://example.com/"],
    engine="meta",
    mappings={"fld_title": ["og:title", "<title>"]},
    fields=[{"fieldId": "fld_title", "name": "title", "type": "string"}],
    scope={"maxUrlsPerExecution": 1, "maxDepth": 0},
    politeness={
        "respectRobotsTxt": True,
        "requestsPerSecond": 1.0,
        "userAgent": "YourCrawler/1.0 (+https://your-domain.example/contact)",
    },
)
print(result.records)
```

The `workspace` extra adds DuckDB and PyArrow as Python dependencies; there is
no database server to operate. Use the `Workspace` API below for durable storage.

Network requests reject loopback, private, link-local, reserved, and
instance-metadata address ranges by default. For an explicitly trusted intranet or
local test server, callers may opt in with `allow_private_networks=True`.
Never enable that option for untrusted job definitions or URLs. Set a user
agent containing a working operator contact and review the repository's
responsible-crawling policy before using live targets.

This native directory workflow is the default open-source deployment. Docker
is optional; users do not need Docker, Redis, an account, or a background
database service. If the native scheduler is interrupted, its SQLite runner
lease expires (or is released on graceful shutdown) and startup resumes the
durable execution frontier without creating another execution intent.

The following creates a job and enables an hourly schedule; it does not start
the scheduler. Replace the contact placeholder before starting scheduled crawls.

```python
from pulsecrawl import Workspace

with Workspace.init("./my-crawls") as pc:
    dataset = pc.datasets.create(
        "news",
        fields=[{"fieldId": "title", "name": "title", "type": "string"}],
        mode="new_urls_only",
    )
    job = pc.jobs.create(
        "hourly news",
        seeds=["https://example.com/news"],
        dataset_id=dataset["datasetId"],
        templates=[{"engine": "css", "mappings": {"title": "h1"}}],
        scope={
            "maxDepth": 6,
            "maxUrlsPerExecution": 1_000,
            "maxUrlsTotal": 1_000_000,
        },
        politeness={
            "respectRobotsTxt": True,
            "requestsPerSecond": 1.0,
            "userAgent": "YourCrawler/1.0 (+https://your-domain.example/contact)",
        },
    )
    pc.schedules.set(job["jobId"], "4 * * * *", timezone_name="UTC")
```

The workspace is one copyable directory. JSON definitions and Parquet
outputs are human-owned; `state/pulsecrawl.sqlite` supplies transactional
frontiers, URL history, schedules, budgets, robots caching, and shared
workspace/site rate limits. Python memory is used only as an L1 cache. Redis
is not required and SQLite remains authoritative after restarts.

```bash
pulsecrawl -w ./my-crawls schedule start
pulsecrawl -w ./my-crawls dataset query ds_... \
  "SELECT * FROM dataset WHERE _crawled_at >= now() - INTERVAL 1 HOUR"
pulsecrawl -w ./my-crawls dataset urls ds_... --newness repeat
pulsecrawl -w ./my-crawls execution urls exec_... --newness new
pulsecrawl -w ./my-crawls job show job_...
pulsecrawl -w ./my-crawls dataset compact ds_...
pulsecrawl -w ./my-crawls dataset prune ds_... --keep-versions 30
```

Local data uses immutable hourly parts and version manifests:

```text
datasets/{datasetId}/
├── manifests/current.json
├── manifests/versions/{version}-{change}.json
└── data/ingest_date=YYYY-MM-DD/hour=HH/
    ├── delta-{executionId}.parquet
    └── compact-{contentId}.parquet
```

`ingest_date` and `hour` describe when the execution committed the part;
`_crawled_at` is the exact page HTTP-response time. For hourly notifications,
query `_crawled_at` (and `_is_new_url` when desired), so a long crawl that
crosses an hour boundary is still semantically correct.

Compaction replaces files only in the new manifest. Older physical parts are
retained because historical dataset versions still reference them. Retention
can remove old version manifests and files no longer referenced by any retained
version. Pruning is a dry run unless `--apply` is supplied; the Python API uses
`keep_versions` and returns dataset-relative manifest paths in `versionsDeleted`.
The current pointer uses `manifest` to identify its version manifest. Readers,
retention, and workspace repair also support legacy `manifests/snapshots/`
files and the old `snapshot` pointer key without moving historical files.
`keep_snapshots` and `--keep-snapshots` remain compatibility aliases.
SQLite is intended for one host (including several processes on that host) and
must live on local disk, not NFS. The local SQLite backend does not support
multi-host execution.

The local Python and CLI resources cover the product workflow, field, schema,
template, dataset and job definitions; execution/resume; schedules; Parquet
files and versions; SQL; URL pages; and compaction. Their JSON snapshots plus
SQLite and Parquet live entirely inside the workspace directory.

The repository's Docker scheduler runs as an unprivileged user, has a bounded
workspace-validation health check, and uses Docker's `none` log driver. Job
and execution state remains inspectable through the CLI and JSON snapshots
without sending console logs to a metered service.

Runnable examples and recipe libraries live in [examples/](examples/).
After downloading the repository examples and installing the published package,
start without network access with `python -m examples.local_quickstart` or
`python -m examples.workspace_quickstart --workspace ./quickstart-workspace`.
See the [example guide](examples/README.md) for shared structure, live opt-in flags,
and offline validation commands.

External agents can help compile and validate deterministic templates without
becoming part of crawl-time extraction. The local workspace provides governed
representative sampling, structure-only page inspection, inactive versioned
drafts, positive and negative validation, contamination and provenance
diagnostics, explicit approval, immutable promotion, and drift repair. See
[Agent-assisted template authoring](docs/AgentTemplateAuthoring.md)
and [the generic example](examples/agent_template_authoring.py).

## Architecture and contributing

This repository publishes one Python distribution and one import namespace.
The inner `src/` directory is the standard Python packaging layout, not a
second package or deployable service. PulseCrawl uses hexagonal architecture:

```text
src/pulsecrawl/
├── domain/                Models, invariants, and pure policies
├── application/           Use cases and ports (interfaces)
├── adapters/
│   ├── inbound/           Python API, CLI, and scheduler process
│   └── outbound/          HTTP, HTML, SQLite, files, Parquet, and DuckDB
├── bootstrap/             Dependency wiring and resource ownership
└── core/                  Legacy compatibility imports
```

Dependencies point inward: domain has no infrastructure dependencies, and
application coordinates work through ports rather than accessing databases,
files, or HTTP clients directly. Focused classes own orchestration and
lifecycle; stateless policies remain functions where that is simpler.
The old `core` and top-level module paths are compatibility imports, not
duplicate implementations.

The [crawl engine](src/pulsecrawl/application/crawling/engine.py) coordinates
URL admission, dispatch, page processing, and record extraction. Requests run
through the [HTTP fetcher](src/pulsecrawl/adapters/outbound/http/fetcher.py), and
scraping strategies live in [HTML extraction](src/pulsecrawl/adapters/outbound/html/extraction/).
Python and CLI entry points use the same engine through local adapters.
Existing public imports and workspace formats are preserved.

See the [architecture guide](docs/PackageArchitecture.md) for the component map,
dependency rules, durability contracts, and extension points. Follow
[CONTRIBUTING.md](CONTRIBUTING.md) for editable installs and tests; the suite
enforces a 90% coverage gate. The [workspace soak tool](tools/soak_workspace.py)
also checks completeness, compaction, and backup/restore.
Release maintainers should follow the [PyPI publishing guide](docs/PyPI.md).
The index description is maintained in [PYPI_README.md](PYPI_README.md);
changes there appear on PyPI only when a new version is published.

## License

`pulsecrawl` is licensed under the [GNU Affero General Public License v3.0](LICENSE).
