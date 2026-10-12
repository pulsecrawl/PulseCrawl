# Responsible crawling

PulseCrawl is designed for authorized, identifiable, rate-limited collection.
Operators remain responsible for deciding whether they may access and retain a
site's material.

## Before running a crawl

- Crawl only systems you own, administer, or have permission to access.
- Review the site's robots policy, terms, applicable law, copyright, privacy,
  and contractual restrictions. Robots permission is not legal permission.
- Use the smallest useful scope, depth, request budget, and schedule.
- Set a truthful user agent with a working operator contact, for example
  `MyResearchBot/1.0 (+https://example.org/crawler)`.
- Avoid collecting credentials, private records, personal data, or content that
  you are not prepared to secure and delete.

PulseCrawl honors robots.txt by default and shares per-origin request pacing.
Do not disable those controls to bypass publisher policy or access controls.

## Network boundary

The default HTTP adapter rejects loopback, private, link-local, multicast,
reserved, documentation, and cloud-metadata address ranges after DNS
resolution. This applies to seeds, robots files, discovered links, and redirect
destinations because they all use the same bounded adapter.

Local callers may set `allow_private_networks=True` only for an explicitly
trusted intranet or local test server. Never enable it for job definitions,
URLs, or redirects supplied by an untrusted party. Hosted deployments should
also enforce outbound firewall policy as defense in depth.

## Live examples

Recipes under `./examples` record selectors and robots
observations at a point in time. Websites change without notice. Treat these as
best-effort examples, re-check current permission and robots policy, and run
them only with explicit network opt-in by the operator.

## Incident response

Stop the crawl if a publisher reports harm, scope appears broader than intended,
or sensitive data is collected. Preserve only the minimal diagnostic record,
remove improperly retained content, and follow the reporting process in
`SECURITY.md` for a product vulnerability.
