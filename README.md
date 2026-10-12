# pulsecrawl

The PulseCrawl SDK. Two modes, one engine:

This repository publishes one Python distribution and one import namespace.
The reusable crawler lives in `src/pulsecrawl/application/crawling`.
`domain` contains pure policies, `application` orchestrates use cases through
ports, `adapters` implements Python/CLI, HTTP, SQLite and file integrations,
and `bootstrap` wires those components together. The old `core` and top-level
module paths remain compatibility imports, not duplicate implementations.
The inner `src/` directory is the standard Python packaging layout, not a
second package or deployable service.

See the [package architecture](docs/PackageArchitecture.md) for the
dependency rules, crawl pipeline, durability contracts, and extension points.

## Architecture at a glance

PulseCrawl uses hexagonal architecture inside a single package:

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

The [crawl engine](src/pulsecrawl/application/crawling/engine.py) coordinates
URL admission, dispatch, page processing, and record extraction. Actual
requests run through the [HTTP fetcher](src/pulsecrawl/adapters/outbound/http/fetcher.py),
and scraping strategies live in [HTML extraction](src/pulsecrawl/adapters/outbound/html/extraction/).
Local and hosted callers supply different adapters to the same engine;
hosted authentication, billing, web UI, and cloud dispatch remain outside
the public package. Existing public imports and workspace formats are preserved.

Regression, architecture-boundary, and adapter-contract tests run with
`python -m pytest` from the package root, with a 90% coverage gate.
The [workspace soak tool](tools/soak_workspace.py) also checks record
completeness, compaction, and backup/restore. See the
[architecture guide](docs/PackageArchitecture.md) for the full component map
and durability contracts.

## Local and hosted usage

The first PyPI release is being prepared; the commands below install from
source. Release maintainers should follow the [PyPI publishing guide](docs/PyPI.md).
The package-index description is maintained separately in [PYPI_README.md](PYPI_README.md)
so its links work outside GitHub.

**Local: free, no account.** Crawl in memory with the exact engine the hosted
product runs, or use a portable workspace for durable SQLite state, Parquet
dataset versions, embedded DuckDB queries, and hourly schedules:

```python
from pulsecrawl import crawl

result = crawl(
    seeds=["https://example.com/"],
    engine="meta",
    mappings={"fld_title": ["og:title", "<title>"]},
    fields=[{"fieldId": "fld_title", "name": "title", "type": "string"}],
    dataset="./my-data/pages",  # optional folder: runs accumulate in the
)                               # same executions/ layout the cloud uses
print(result.records)
```

Install the complete local runtime from the package directory (DuckDB and
PyArrow are Python packages; there is no database server to operate):

```bash
python -m pip install -e .
python -m pip install -e '.[workspace]'
pulsecrawl init ./my-crawls
```

Network requests reject loopback, private, link-local, reserved, and cloud
metadata address ranges by default. For an explicitly trusted intranet or
local test server, callers may opt in with `allow_private_networks=True`.
Never enable that option for untrusted job definitions or URLs. Set a user
agent containing a working operator contact and review the repository's
responsible-crawling policy before using live targets.

This native directory workflow is the default open-source deployment. Docker
is optional; users do not need Docker, Redis, a cloud account, or a background
database service. If the native scheduler is interrupted, its SQLite runner
lease expires (or is released on graceful shutdown) and startup resumes the
durable execution frontier without creating another execution intent.

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
must live on local disk, not NFS. Multi-host execution uses the hosted cloud
adapters or a separately configured distributed backend.

The local Python and CLI resources cover the product workflow, field, schema,
template, dataset and job definitions; execution/resume; schedules; Parquet
files and versions; SQL; URL pages; and compaction. Their JSON snapshots plus
SQLite and Parquet live entirely inside the workspace directory. Hosted-only
concerns such as organizations, API keys, Firebase authentication, the web
console, multi-machine dispatch, and SAS download links intentionally stay in
the paid control plane.

The repository's Docker scheduler runs as an unprivileged user, has a bounded
workspace-validation health check, and uses Docker's `none` log driver. Job
and execution state remains inspectable through the CLI and JSON snapshots
without sending console logs to a metered service.

**Hosted: crawls run in the cloud** and results become durable, queryable
Parquet datasets:

```python
from pulsecrawl import PulseCrawl

pc = PulseCrawl(
    api_key="pk_live_...",
    base_url="https://api.example/v1",
)
job = pc.jobs.create(
    "multi-site news",
    seeds=["https://one.example/news", "https://two.example/latest"],
    template_stack=[
        {
            "template_id": "tmpl_one_article",
            "hosts": ["one.example"],
            "url_patterns": ["/news/*"],
        },
        {
            "template_id": "tmpl_two_article",
            "hosts": ["two.example"],
            "url_patterns": ["/articles/*"],
        },
    ],
    scope={
        "max_depth": 6,
        "max_urls_per_execution": 1_000,
        "max_urls_total": 1_000_000,
    },
    dataset_id=pc.datasets.create(
        "pages",
        schema_id="schema_sys_page_summary_v1",
        mode="new_urls_only",
        identity_field="_source_url",
    )["datasetId"],
)
execution = pc.jobs.run(job["jobId"])
final = pc.executions.wait(execution["executionId"])
print(pc.datasets.files(job["datasetId"]))
```

Every execution starts a new queue frontier from the seeds. The per-execution
frontier admits at most `maxUrlsPerExecution` unique URLs, so page HTTP attempts
can never exceed that bound. The cumulative limit is settled from actual page
HTTP attempts, including failed responses; robots/depth skips do not consume
the cumulative capacity. A scheduled job
therefore runs with up to 1,000 attempts each hour until its cumulative one
million-attempt ceiling is reached.

Hosted mode intentionally has no built-in service endpoint. Pass `base_url`
explicitly or set `PULSECRAWL_BASE_URL`; this prevents an installed SDK from
silently sending credentials or job definitions to a development deployment.

### Connect an OSS workspace to cloud

Cloud access is explicit and profile-based. Install the optional keyring
integration, create a least-privilege key in the hosted console, and connect it
to a named profile. The profile JSON contains only endpoint, organization, and
key identifiers; the secret is stored in the operating-system credential
store. CI may provide `PULSECRAWL_API_KEY` instead; when that variable is set,
`cloud connect` writes only the non-secret profile metadata and does not require
or modify a keyring backend.

```bash
python -m pip install -e '.[workspace,cloud]'
pulsecrawl cloud connect --profile production --base-url https://api.example/v1
pulsecrawl cloud whoami --profile production

# Preview and then idempotently import local definitions.
pulsecrawl -w ./my-crawls cloud plan --profile production
pulsecrawl -w ./my-crawls cloud push --profile production

# Import definitions, map the local job ID, and start its cloud execution.
pulsecrawl -w ./my-crawls cloud run job_local_id --profile production

# Download the active, version-consistent Parquet snapshot. Signed artifact
# requests never receive the PulseCrawl API key.
pulsecrawl cloud pull ds_cloud_id ./cloud-results --profile production
```

`cloud plan` refuses duplicate names, dangling references, and incompatible
same-name resources. `cloud push` preserves field/schema/template/dataset/job
relationships, URL-scoped template stacks, and paused schedules. It does not
upload credentials or silently contact cloud from a local command. Hosted
mutations use stable per-request idempotency keys and retry only transient
transport/429/502/503/504 failures; reads use bounded exponential backoff and
honor `Retry-After`.

Hosted crawling always honors robots.txt. Request pacing is shared by website
across every job in the organization, so two jobs targeting the same origin do
not each receive a separate allowance. A separate platform-wide origin gate
provides a safety floor across organizations, and a robots `Crawl-delay` can
only slow that origin further. Every scheduled and final dispatch interval has
a 10% conservative margin. The configured rate remains a maximum: this small
throughput reserve reduces client-dispatch-to-wire jitter from compressing the
spacing observed by an origin, without claiming control over arbitrary network
reordering. Owners can inspect or change their organization
ceiling through the SDK:

```python
org = pc.organizations.get("org_...")
print(org["rateLimits"]["requestsPerSecondPerWebsite"])
pc.organizations.update(
    org["orgId"], requests_per_second_per_website=1,
)
```

SQL reads all committed Parquet parts across all executions. URL history is
also directly pageable without writing SQL:

```python
for item in pc.datasets.iter_urls(job["datasetId"], newness="repeat"):
    print(item["urlIdentity"], item["executionCount"], item["lastSeenAt"])

for item in pc.executions.iter_urls(final["executionId"], newness="new"):
    print(item["url"], item["isNew"])
```

Dataset URL pages use the durable identity ledger. `newness="new"` means the
identity has appeared in one execution; `newness="repeat"` means it has
appeared in more than one. Execution pages use that run's `_is_new_url` value.
`new_urls_only` suppresses a URL only when it appeared in a prior execution;
if a first-seen page yields multiple legitimate entities, all of them remain.
Use a schema field ID with type `url` as `identity_field` when canonical URLs
are extracted separately from `_source_url`.

Schedules use semantic five-field cron expressions, IANA time zones, and a
minimum cadence of one hour:

```python
schedule = pc.schedules.set(
    job["jobId"],
    "0 9 * * 1-5",
    timezone="America/Denver",
)
print(schedule["nextRunAt"])
pc.schedules.pause(job["jobId"])
pc.schedules.resume(job["jobId"])
```

Each authored template is tried only on matching final URLs. If the entire
authored stack misses, the service tries compatible system templates and marks
that host as `needsTemplate` in the execution's `templateCoverage` report.

Runnable examples and recipe libraries live in [examples/](examples/).
Start without network access with `python -m examples.local_quickstart` or
`python -m examples.workspace_quickstart --workspace ./quickstart-workspace`.
The hosted quickstart prints a plan unless `--apply` is supplied. See the
[example guide](examples/README.md) for shared structure, live opt-in flags,
and offline validation commands.

External agents can help compile and validate deterministic templates without
becoming part of crawl-time extraction. The local workspace provides governed
representative sampling, structure-only page inspection, inactive versioned
drafts, positive and negative validation, contamination and provenance
diagnostics, explicit approval, immutable promotion, and drift repair. See
[Agent-assisted template authoring](docs/AgentTemplateAuthoring.md)
and [the generic example](examples/agent_template_authoring.py).

## License

`pulsecrawl` is licensed under the [GNU Affero General Public License v3.0](LICENSE).
