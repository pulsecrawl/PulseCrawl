# Governance

PulseCrawl uses a repository-administrator governance model. People with
administrative access decide releases, security fixes, compatibility policy,
and the project roadmap after considering public technical discussion. Named
maintainers, when any are publicly designated, are listed in `MAINTAINERS.md`.

## Changes

Routine changes use pull requests with tests and documentation appropriate to
their risk. Changes to public APIs, persisted formats, crawl-safety invariants,
licensing, governance, or the security model require explicit maintainer
or repository-admin approval and a written compatibility or migration note.

Contributions use the Developer Certificate of Origin sign-off described in
`CONTRIBUTING.md`. The project does not currently require a separate contributor
license agreement.

## Releases

Repository administrators select the release commit, verify release
requirements, publish signed/tagged release notes, and may withdraw a release
with a known critical safety or supply-chain defect. Supported versions are
listed in `SECURITY.md`.

## Amendments

Governance changes are proposed by pull request and require repository-admin
approval. If the project gains multiple active maintainers, this file must be
updated with quorum, succession, and conflict-resolution rules.
