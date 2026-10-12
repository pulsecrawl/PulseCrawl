# Security policy

PulseCrawl processes untrusted URLs, HTML, extraction rules, SQL, queue
messages, and dataset metadata. Treat every boundary as hostile even in a
development deployment.

## Supported versions

Security fixes are currently made on the default branch. No tagged version is
declared supported until the first public release is frozen.

## Reporting a vulnerability

Do not open a public issue for a vulnerability, credential, private dataset,
or exploitable URL. Use the private **Report a vulnerability** workflow at
`https://github.com/pulsecrawl/PulseCrawl/security/advisories/new`. Include the
affected commit, deployment mode, reproduction steps, impact, and whether any
secret or third-party system was touched. Do not test against infrastructure
or websites that you do not own or have permission to assess.

## Secret and incident handling

- Never commit API keys, storage keys, Firebase service accounts, SAS tokens,
  signed institutional documents, private crawl bodies, or production logs.
- Environment files may contain only non-secret identifiers. Runtime secrets
  belong in the deployment platform's secret store or local process
  environment.
- If a secret is exposed, revoke or rotate it first; removing it from Git does
  not invalidate it.
- Runtime logging should exclude response bodies, credentials, signed URLs,
  and other sensitive crawl material.

## Security invariants

The current threat model is maintained in
[`docs/ThreatModel.md`](docs/ThreatModel.md). Pull requests that affect URL
fetching, redirects, robots evaluation, tenant authorization, DuckDB, dataset
manifests, credentials, queues, or deletion must add tests at the relevant
boundary and update that model when assumptions change.
