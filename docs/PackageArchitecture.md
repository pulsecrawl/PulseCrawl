# Package architecture

PulseCrawl ships one Python distribution and import namespace, `pulsecrawl`.
Local crawling, portable workspaces, the CLI, and the hosted API client are
different entry points, not separate copies of the engine. Python's inner
`src/` directory is a packaging convention, not another service.

## Layers and dependency rules

All paths below are relative to the installed `pulsecrawl` namespace.

```text
pulsecrawl/
  domain/                      Pure models, invariants and policies
    crawling/                  Intent, URL scope, pacing and retry decisions
    templates/                 Selection, coercion and draft transitions
    executions/                Lifecycle and lifetime-budget policies
    datasets/                  Dataset URL identity
    scheduling/                Deterministic scheduled execution identity
    synchronization/           Workspace comparison and profile values
    workspace/                 Definition normalization
  application/                 Use cases and their required interfaces
    ports/                     Crawling, workspace and cloud Protocols
    crawling/                  Admission, dispatch, pages, records and robots
    templates/                 Resolution, validation and authoring
    datasets/                  Definitions and publication ordering
    executions/                Run, resume, cancellation and settlement
    scheduling/                Due dispatch and abandoned-run recovery
    synchronization/           Profile and remote workspace operations
    workspace/                 Catalogs, jobs, validation and maintenance
  adapters/
    inbound/                   Python facade, CLI and scheduler process
    outbound/                  HTTP, HTML, memory, SQLite, filesystem,
                               Parquet, DuckDB, cron and credentials
  bootstrap/                   Concrete dependency wiring and ownership
  core/                        Compatibility imports only
```

Dependencies point inward: adapters depend on application ports and domain
models; application depends only on domain and its own ports; domain depends
only on the standard library. Only bootstrap selects and assembles concrete
implementations. Domain and application must import without SQLite, HTTP,
HTML parsers, DuckDB, PyArrow, croniter, keyring, or cloud dependencies.

The top-level public API is lazy-loaded. Existing `pulsecrawl.core.*` and
top-level module imports are compatibility bridges. They should not receive
new business logic or be imported from canonical inner layers. A few bridge
classes supply historical defaults or synchronous behavior rather than
being simple module aliases.

Architecture tests enforce these dependency rules and forbid direct SQL and
file operations in application code. Adapter contract tests exercise the
same frontier, admission, pacing and robots semantics against memory and
SQLite implementations. Service tests use fake ports without infrastructure.

## Where crawling and scraping run

The crawl entry point is `application/crawling/engine.py`, `CrawlEngine`.
It runs the queue and coordinates focused components:

| Component | Responsibility |
| --- | --- |
| `FrontierAdmissions` | Scope, unique admission budget, seeds and URL publication |
| `CrawlDispatch` | Readiness, rate reservations and deferral without consuming another URL slot |
| `CrawlPageProcessor` | One page's fetch, redirects, retries, snapshots, extraction and discovered links |
| `RobotsService` | Robots policy through injected fetching, caching and time ports |
| `TemplateSelection` | Pure applicability and precedence decisions |
| `TemplateResolver` | Shared extraction merging, provenance and conflict reporting |
| `RecordExtractor` | Conversion of extracted values to schema field types |

Actual network I/O is in `adapters/outbound/http/fetcher.py`.
HTML scraping is in `adapters/outbound/html/extraction/`: CSS, JSON-LD and
metadata engines. `html/links.py` handles discovered links. These implement
the parser and extractor ports; the crawl application does not import them.

`bootstrap/crawling.py` supplies standard HTML strategies and a durable local
runtime. `bootstrap/ephemeral.py` supplies the memory-backed runtime. Hosted
workers can supply distributed frontier, ledger, gate and sink adapters to
the same engine without depending on the local workspace implementation.

## Lifecycle, time and durability contracts

- `ExecutionService` orchestrates lifecycle through repositories, leases,
  runtime factories, snapshots and task control. It receives narrow
  dependencies, not a whole workspace or raw database connection.
- `Execution` and `BudgetReservation` enforce state and budget rules.
  `freeze_intent` permits only downward execution-limit overrides. SQLite
  preparation freezes intent, reserves lifetime capacity and inserts the
  execution in one transaction. Terminal settlement updates execution state
  and the job budget in one transaction and does not charge a reservation
  twice.
- Unique admission is not the same as successful completion. Retries and
  deferrals keep the admitted URL's slot. Runtime startup reconciles URLs
  admitted before a crash but not yet published to the frontier.
- Readiness deadlines must use the same clock coordinate as their gate and
  frontier. Local durable adapters use epoch seconds so deadlines survive
  process restarts; memory adapters use their clock's readiness coordinate.
  Elapsed timing must use a monotonic timer. Legacy clocks remain supported
  through the explicit readiness helper.
- A record sink may stage records before final publication. The driver
  flushes governed work before terminal settlement. SQLite staging is
  execution-scoped and replayable; a page snapshot is not evidence that a
  dataset manifest has committed.
- `DatasetPublicationService` orders publication: durable immutable Parquet
  file first, manifest visibility second, successful execution settlement
  last. Stable execution change IDs allow publication retries. Compaction
  publishes a new version; it does not delete files referenced by old
  manifests. Retention remains explicit and dry-run by default.
- Graceful cancellation can publish completed partial work; force
  cancellation discards staging. Process shutdown leaves a resumable running
  execution rather than reporting success. Lease and task cleanup also run
  if runtime construction fails.
- Resource factories close transports they construct, including partial
  setup failures. Caller-supplied fetchers remain caller-owned. Filesystem,
  DuckDB, credential and network security boundaries stay in their adapters.

## Workspace, authoring and hosted boundaries

The `Workspace` facade is a small inbound API. Catalog, job, dataset,
authoring, schedule and execution services own their use cases; bootstrap
wires JSON repositories, SQLite transactions, local files and parser
strategies. JSON snapshots remain human-readable projections of state.

Template drafts own validation/approval/promotion transitions. Authoring and
runtime use the same template resolution service, so validation does not
have a second implementation of extraction precedence.

Schedules separate due-claim persistence, cron calculation and process
signals. The synchronous workspace scheduler invokes synchronous inbound
job/execution facades; async callers use application services directly.

`WorkspaceSyncPlanner` is pure comparison. `WorkspaceSyncService` uses a
hosted gateway; HTTP resources implement that gateway. `ProfileService`
separates non-secret metadata from credentials. Signed artifact downloads
use a separate client and never inherit the hosted API key.

Hosted-only authentication, organizations, billing, web UI, cloud dispatch
and distributed persistence remain outside the public package. Keeping one
distribution does not require putting those systems into it. Local and
hosted lifecycles can differ while sharing crawl policies and ports.

## Extending and validating

Add pure rules to domain, orchestration to application, and technology-specific
implementations to outbound adapters. Introduce a class when it owns state,
an invariant, a strategy or a useful dependency seam; keep stateless policies
as functions instead of adding classes solely to make everything OOP.
Supply concrete dependencies in bootstrap and expose user-facing behavior
through an inbound adapter. Do not add a second distribution just to create
an internal boundary.

From the package root, run `python -m pytest` for regression, boundary,
service and adapter-contract tests. The existing coverage gate remains 90%.
`tools/soak_workspace.py` exercises completeness, compaction and backup/restore
at larger volumes. The private repository additionally tests its hosted
worker against this same package; hosted services are not exported.

Public imports, CLI commands, workspace layout, SQLite schema and manifest
formats remain compatible with the pre-refactor implementation. New code
should target canonical layers; compatibility bridges can be deprecated
separately once a supported release policy requires it.
