# PulseCrawl threat model

This document covers the open-source code in this repository: the crawl
engine, local SDK and workspace, Parquet datasets, embedded DuckDB queries,
template authoring, and the optional hosted API client. Hosted-service
implementation details are outside this repository and are not security
claims of the open-source project.

## Assets and trust boundaries

| Boundary | Protected assets | Untrusted inputs | Required controls |
|---|---|---|---|
| Outbound requests | local network, publisher availability, request budgets | seeds, discovered links, redirects, DNS answers, robots responses | URL normalization and scope, robots checks, per-origin pacing, DNS/IP classification, response limits |
| Extraction | typed records and provenance | HTML, JSON-LD, metadata, selectors, literals | URL-scoped templates, type coercion, bounded parsing, explicit fallback provenance |
| Local workspace | SQLite state, definitions, retained pages, schedules | job definitions, downloaded content, interrupted processes | explicit workspace root, transactional state, atomic writes, runner leases, filesystem permissions |
| Dataset and query | Parquet parts, manifests, query resources | records, schemas, SQL, corrupt or stale files | immutable versions, atomic manifest publication, dataset-scoped files, memory/thread/row limits |
| Template authoring | drafts, validation evidence, promoted templates | webpage content and external-agent output | offline inspection, positive and negative validation, explicit approval, immutable promotion |
| Hosted client | API credentials and downloaded artifacts | endpoints, API responses, signed download URLs | explicit HTTPS endpoint, OS credential storage, bounded retries, no API key on artifact hosts |

## Principal threats and mitigations

### Server-side request forgery and redirect escape

URLs can target private services or redirect outside the intended scope. The
default HTTP adapter rejects loopback, private, link-local, multicast,
reserved, documentation, and cloud-metadata address ranges, including DNS
answers in those ranges. Redirects return to the crawl engine so scope,
robots, and pacing are checked again before another request.

`allow_private_networks=True` is an explicit local opt-in for trusted intranet
or test targets. Do not expose it to untrusted job authors. Custom fetchers are
responsible for providing equivalent protections.

### Publisher overload and unintended scope

Every execution has depth and URL budgets, and durable jobs also have a
lifetime budget. Robots policy is enabled by default and request pacing is
shared by origin within a workspace. Operators must still choose lawful,
authorized targets and conservative limits; technical access is not
permission to collect or retain content.

### Malicious or malformed content

Response bodies, metadata, JSON-LD, and selector results are untrusted. Fetch
and parsing limits bound memory use. Extraction performs type coercion and
records provenance, but a syntactically valid result can still be semantically
wrong. Applications should validate critical fields and avoid treating
extracted text as instructions.

### Workspace corruption and crash recovery

SQLite transactions coordinate local execution state. Parquet parts are
published through immutable version manifests and an atomic current pointer.
Runner leases allow interrupted work to resume, but a hard crash at an HTTP
boundary can repeat a remote request. The system guarantees convergent local
state, not exactly-once network effects.

Keep a workspace on local disk and back up the entire directory. A local
workspace is not a multi-host consensus system and must not be shared over
NFS.

### SQL and resource exhaustion

Queries operate on files selected from a dataset manifest and apply bounded
threads, memory, execution time, rows, and pagination. These controls reduce
accidental or adversarial resource use but do not replace operating-system
isolation when SQL comes from an untrusted user.

### Data and credential disclosure

Hosted artifact paths are validated before filesystem writes. Descendant
symlinks/reparse points are rejected, and parent directories remain pinned
through staging and publication. Downloads publish with an atomic no-clobber
rename unless the caller explicitly requests overwrite. Duplicate or ambiguous
cross-platform paths and negative declared sizes are rejected before downloads.
The destination itself is caller-selected and trusted; these controls do not
isolate a workspace from a malicious user with equivalent filesystem access.

Raw-page persistence is optional. Logs, bug reports, and shared workspaces
must not include response bodies, authorization headers, API keys, cookies,
signed URLs, or private records. Cloud profile JSON contains identifiers only;
the optional hosted-client secret belongs in the operating-system credential
store or an explicit CI environment variable.
Profile metadata is written with mode `0600` on POSIX. On Windows it inherits
the containing directory's ACL; `chmod` does not establish a private Windows
ACL. Keep configuration in a user-controlled directory on either platform.

### Agent-assisted template authoring

Page text that resembles instructions remains untrusted data. Sampling uses a
normal bounded crawl. Inspection and validation make no network requests, and
promotion requires an explicitly approved passing validation. External agents
must not receive credentials or tools that can expand crawl scope, change
budgets, disable robots handling, approve drafts, or promote templates.

## Residual risks

- Custom fetchers and private-network opt-in can bypass default network
  protections.
- A crash can repeat a completed remote request before its local outcome is
  committed.
- Templates can produce plausible but semantically incorrect records.
- A user with filesystem access can read or alter a local workspace.
- Live websites, robots policies, and terms can change without notice.

## Validation checklist

- Run package tests, dependency audits, and `python3 scripts/check-secrets.py`.
- Exercise literal and DNS-resolved private-address rejection.
- Verify redirects and robots decisions before each destination request.
- Test execution and lifetime budgets, response-size limits, and pacing.
- Inject failures around SQLite commits and manifest publication.
- Test query file scoping, cancellation, and resource limits.
- Review retained pages, logs, profiles, and exported artifacts before sharing.
