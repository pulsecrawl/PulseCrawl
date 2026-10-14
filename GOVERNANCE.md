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

## Repository access and ownership

The project account `@pulsecrawl` is currently the sole repository administrator
and the code owner for every path in `.github/CODEOWNERS`. Public contributors
may open issues and pull requests, but cannot push or merge without repository
write access. Code ownership routes review requests; it does not grant access.
Additional write access is granted explicitly by the repository administrator
after evaluating a contributor's work and trustworthiness.

Changes to `main` require a pull request, passing required CI checks on an
up-to-date branch, and resolved review conversations. Independent approval and
last-push approval are currently optional so the sole administrator can merge
their own pull requests after validation. Administrator enforcement and the
protections against force pushes and branch deletion remain enabled. Review
these settings before granting additional write access; require code-owner
approval if trusted contributors should not be able to merge without it.
Package-publication safeguards are separate and remain unchanged.

## Releases

Repository administrators select the release commit, verify release
requirements, publish signed/tagged release notes, and may withdraw a release
with a known critical safety or supply-chain defect. Supported versions are
listed in `SECURITY.md`.

## Amendments

Governance changes are proposed by pull request and require repository-admin
approval. If the project gains multiple active maintainers, this file must be
updated with quorum, succession, and conflict-resolution rules.
