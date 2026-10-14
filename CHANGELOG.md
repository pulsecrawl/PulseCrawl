# Changelog

## 0.2.0

- Retry transient Windows atomic snapshot replacement conflicts within a
  bounded window; persistent write failures still surface without deleting
  the previous snapshot.
- Standardize crawl queue terminology as **Pending URLs**, including the
  `PendingUrl` model, `PendingUrls` port, `MemoryPendingUrls` and
  `SQLitePendingUrls` adapters, `PendingUrlAdmissions`, and the
  `EnginePorts.pending_urls` dependency. Low-level integrations must update
  their imports and dependency keyword; top-level `crawl` and `Workspace`
  calls are unchanged. No old-name Python aliases are retained.
- Upgrade SQLite state to schema 5, preserving queued URLs, retry counters,
  readiness times, leases, and FIFO sequence IDs. Existing workspaces receive
  a pre-migration backup automatically; older package versions cannot reopen
  schema-5 workspaces, so keep that backup if a downgrade is required.

## Publishing preparation

- Serialize shared SQLite cursor reads as well as statement execution.
- Flush completed output files with Windows-compatible writable descriptors,
  retain directory write/rename exclusion during downloads, and install Windows
  timezone data for scheduling. Profile metadata uses POSIX modes or inherited
  Windows ACLs; credentials remain outside that file on every platform.
- Generate the CI SBOM outside the checkout so the clean-source release gate
  continues to reject genuine uncommitted source changes.
- Publish Windows downloads with a same-parent native rename so publication
  does not reopen or unlock a parent protected against reparse mutation.
- Pin container aiohttp consistently with the package security floor, and test
  container-lock compatibility to catch future dependency drift.
- Publish downloaded artifacts without clobbering concurrent writers by default;
  pin validated parent directories before creating descendants or staging files.
- Reject ambiguous, duplicate, and platform-specific artifact paths before writes.
- Strip personal ownership/PAX metadata from source archives at build time and
  reject identity leaks or personal maintainer metadata in distribution checks.
- Validate restored workspaces before atomic no-clobber publication; never
  remove or replace a competing backup/restore destination.
- Explicitly reject multicast and special-purpose crawler destinations across
  supported Python versions, including IPv4-mapped IPv6 addresses.
- Raise the aiohttp security floor to 3.14.5 and pytest to 9.0.3 (with compatible
  pytest-asyncio); audit minimum dependencies including transitive packages.
- Use audited setuptools 84 or newer for source builds and backend tests.
- Require successful full CI on the exact tagged SHA and protected publishing
  environments before allowing an upload.
- Add a PyPI-specific description, complete source archives, artifact validation,
  and clean-install smoke checks.
- Prepare manual GitHub OIDC publishing with TestPyPI rehearsal and separate
  production approval. Account, publisher, and environment setup remain launch tasks.

All notable changes to the public PulseCrawl package will be recorded here.
The initial public alpha release is 0.1.0.

## 0.1.1

### Documentation and examples

- Make the PyPI repository link explicitly GitHub and lead installation with
  the published package rather than a source checkout.
- Focus the public guides and examples on local open-source use.
- Add standalone consumers of the published package and retain the eight local
  recipe categories, offline extraction, and controlled price-history demos.
- Correct repository-root example commands and contributor test instructions.

## 0.1.0

### Added

- Import-safe offline memory and workspace quickstarts, shared example
  provisioners, runnable per-category entry points, and offline workflow tests.
- Recipe validation using saved HTML or explicitly opted-in governed sampling;
  no samples checked is inconclusive rather than a successful validation.
- `pulsecrawl.core`, a portable crawl engine with bounded pending URL queues,
  robots handling, request pacing, redirect reauthorization, response-size
  limits, typed extraction, and explicit private-network opt-in.
- Top-level `pulsecrawl` APIs for synchronous local crawling and portable workspaces with SQLite
  state, Parquet datasets, embedded DuckDB queries, schedules, compaction,
  and template authoring.
- Native and Docker-based local operation without a required account,
  Redis deployment, or external database server.
- An allowlisted public-source exporter, cross-platform Python CI, package
  build validation, dependency auditing, SBOM generation, secret scanning,
  and release automation.
- GNU Affero General Public License v3.0 licensing, governance, DCO contribution terms, security
  reporting, community standards, support boundaries, and responsible-use
  guidance.
- A single `pulsecrawl` distribution containing both the engine and SDK,
  replacing the pre-release split-package layout.
- Hexagonal internal layers (`domain`, `application`, `adapters`, `bootstrap`),
  focused crawl services, repository and runtime ports, and executable
  dependency-boundary tests. Existing public imports remain compatible.

### Fixed

- Concurrent preparation of the same execution ID now returns the original
  execution and reserves lifetime capacity only once. Identity lookup,
  reservation, and insertion share one immediate SQLite transaction.

### Safety and compatibility notes

- Network requests reject non-global IPv4 and IPv6 destinations by default,
  including loopback, private, link-local, reserved, and metadata-service
  addresses resolved directly or through DNS.
- Redirect destinations are returned to the crawl engine for scope, robots,
  and origin-rate authorization before the next request.
- PulseCrawl is alpha software. Public compatibility begins with the first
  tagged release; no earlier commit is a supported release.
